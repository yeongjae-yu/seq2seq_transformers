import torch
from torch import nn
from torch.utils.data import Dataset, DataLoader
from transformer_yyj import Transformer, TransformerConfig, Decoders, get_attn_mask, get_look_ahead_attn_mask
from torch import optim
import sentencepiece as spm
from transformers import ElectraModel, ElectraTokenizer


# this is only used with version of sentencepiece tokenizer
def make_feature(src_list, trg_list, tokenizer, config):
    pad = tokenizer.convert_tokens_to_ids(['[PAD]'])
    cls = tokenizer.convert_tokens_to_ids(['[CLS]'])
    sep = tokenizer.convert_tokens_to_ids(['[SEP]'])
    encoder_features = []
    decoder_features = []
    trg_features = []
    max_len = 0
    for i in range(len(src_list)):
        src_text = tokenizer.tokenize(src_list[i])
        trg_text = tokenizer.tokenize(trg_list[i])
        encoder_feature = tokenizer.convert_tokens_to_ids(src_text)
        decoder_feature = cls + tokenizer.convert_tokens_to_ids(trg_text)
        trg_feature = tokenizer.convert_tokens_to_ids(trg_text) + sep
        max_len = max(max_len, len(trg_feature))
        encoder_feature += pad * (config.max_seq_length - len(encoder_feature))
        decoder_feature += pad * (config.max_seq_length - len(decoder_feature))
        trg_feature += pad * (config.max_seq_length - len(trg_feature))
        encoder_features.append(encoder_feature)
        decoder_features.append(decoder_feature)
        trg_features.append(trg_feature)
    print(max_len)
    encoder_features = torch.LongTensor(encoder_features).to(config.device)
    decoder_features = torch.LongTensor(decoder_features).to(config.device)
    trg_features = torch.LongTensor(trg_features).to(config.device)
    return encoder_features, decoder_features, trg_features


class CustomDataset(Dataset):
    def __init__(self, config, lm):
        src_file_path = 'D:/Storage/sinc/tts_script/data_filtering/철자표기.txt'
        trg_file_path = 'D:/Storage/sinc/tts_script/data_filtering/발음표기.txt'
        with open(src_file_path, 'r', encoding='utf8') as f:
            src_lines = list(map(lambda x: x.strip('\n'), f.readlines()))
        with open(trg_file_path, 'r', encoding='utf8') as f:
            trg_lines = list(map(lambda x: x.strip('\n'), f.readlines()))
        self.encoder_input, self.decoder_input, self.target = make_feature(src_lines, trg_lines, lm, config)

    def __len__(self):
        return len(self.encoder_input)

    def __getitem__(self, idx):
        x = self.encoder_input[idx]
        y = self.decoder_input[idx]
        z = self.target[idx]
        return x, y, z


class Spell2Pronunciation(nn.Module):
    def __init__(self):
        super(Spell2Pronunciation, self).__init__()
        # KoELECTRA-Small-v3
        self.encoders = ElectraModel.from_pretrained("monologg/koelectra-small-v3-discriminator")
        self.decoders = Decoders(config)
        self.dense = nn.Linear(config.hidden_size, config.trg_vocab_size)

    def forward(self, encoder_iuputs, decoder_inputs):
        decoder_attn_mask = get_attn_mask(decoder_inputs, self.padding_idx)
        look_ahead_attn_mask = get_look_ahead_attn_mask(decoder_inputs)
        look_ahead_attn_mask = torch.gt((decoder_attn_mask + look_ahead_attn_mask), 0)
        encoder_outputs = self.encoders(encoder_iuputs).last_hidden_states
        decoder_outputs, _, _ = self.decoders(encoder_outputs, decoder_inputs, look_ahead_attn_mask, decoder_attn_mask)
        model_output = self.dense(decoder_outputs)
        return model_output


if __name__ == '__main__':
    tokenizer = ElectraTokenizer.from_pretrained("monologg/koelectra-base-v3-discriminator")
    # inputs = torch.randint(vocab_size, (100, 8), dtype=torch.float, device=config.device)
    # labels = torch.randint(vocab_size, (100, 8), dtype=torch.float, device=config.device)
    src_vocab_size = 35000
    trg_vocab_size = 35000

    config = TransformerConfig(src_vocab_size=src_vocab_size,
                               trg_vocab_size=trg_vocab_size,
                               device='cuda',
                               hidden_size=256,
                               num_attn_head=4,
                               feed_forward_size=1024,
                               max_seq_length=512,
                               share_embeddings=True)
    model = Transformer(config).to(config.device)

    class_weight = torch.tensor([0.001, 0.01, 0.01, 0.01])
    preserve = torch.ones(trg_vocab_size - class_weight.size()[0])
    class_weight = torch.cat((class_weight, preserve), dim=0).to(config.device)
    criterion = nn.CrossEntropyLoss(weight=class_weight)
    optimizer = optim.Adam(model.parameters(), lr=1e-5)

    total_epoch = 1
    dataset = CustomDataset(config, tokenizer)
    dataloader = DataLoader(dataset, batch_size=8, shuffle=True)

    model.train()
    for epoch in range(total_epoch):
        total_loss = 0
        for iteration, datas in enumerate(dataloader):
            encoder_inputs, decoder_inputs, targets = datas
            optimizer.zero_grad()
            logits, _ = model(encoder_inputs, decoder_inputs)
            logits = logits.contiguous().view(-1, trg_vocab_size)
            targets = targets.contiguous().view(-1)
            # indices = targets.nonzero().squeeze(1)
            # logits = logits.index_select(0, indices)
            # targets = targets.index_select(0, indices)
            loss = criterion(logits, targets)
            loss.backward()
            optimizer.step()
            total_loss += loss
            # if (iteration + 1) % 50 == 0:
            #     print('Iteration: %3d \t' % (iteration + 1), 'Cost: {:.5f}'.format(loss))
        # break
        # if (epoch + 1) % 5 == 0:
        print('Epoch: %3d\t' % (epoch + 1), 'Cost: {:.5f}'.format(total_loss/(iteration + 1)))
        # if (epoch + 1) % 100 == 0:
    model_path = './model_weight/transformer_%d' % (epoch + 1)
    torch.save(model.state_dict(), model_path)

    # model.load_state_dict(torch.load('./model_weight/transformer_10'))
    model.eval()
    sample_encoder_input = ['나는 안녕하세요 1+1 이벤트 진행 중이다, 가격 1300원이야.',
                            '가랑비에 옷 젖는 줄 모른다.',
                            '고객님, 현재 짜파게티는 1+1 상품으로 이벤트가 진행중이니 살펴보고 가세요.']
    sample_decoder_input = [''] * len(sample_encoder_input)
    sample_encoder_input, sample_decoder_input, _ = make_feature(sample_encoder_input, sample_decoder_input,
                                                                 tokenizer, config)
    predicts, _ = model(sample_encoder_input, sample_decoder_input)
    print(predicts.size())
    predicts = torch.max(predicts, dim=-1)[-1].long().to('cpu')

    for predict in predicts:
        predict = predict.numpy()
        print('predict size:', predict.shape)
        predict = list(map(int, predict))
        predict = tokenizer.convert_ids_to_tokens(predict)
        print('예측 결과:', tokenizer.convert_tokens_to_string(predict))