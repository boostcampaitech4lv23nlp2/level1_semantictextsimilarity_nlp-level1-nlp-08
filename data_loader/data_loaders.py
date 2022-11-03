import re

import pandas as pd
import pytorch_lightning as pl
import torch
import transformers
from sklearn.model_selection import KFold, StratifiedShuffleSplit
from tqdm.auto import tqdm


class Dataset(torch.utils.data.Dataset):
    def __init__(self, inputs, targets=[]):
        self.inputs = inputs
        self.targets = targets

    def __getitem__(self, idx):
        if len(self.targets) == 0:
            return torch.tensor(self.inputs[idx])
        else:
            return torch.tensor(self.inputs[idx]), torch.tensor(self.targets[idx])

    def __len__(self):
        return len(self.inputs)


class Dataloader(pl.LightningDataModule):
    def __init__(
        self,
        model_name,
        batch_size,
        train_ratio,
        shuffle,
        train_path,
        test_path,
        predict_path,
        swap,
    ):
        super().__init__()
        self.model_name = model_name
        self.batch_size = batch_size
        self.train_ratio = train_ratio
        self.shuffle = shuffle

        self.train_path = train_path
        self.test_path = test_path
        self.predict_path = predict_path

        self.train_dataset = None
        self.val_dataset = None
        self.test_dataset = None
        self.predict_dataset = None

        ## 손으로 수정하는 부분 좀 줄일 수 있게끔 수정
        model_list = {
            "bert": [
                "klue/roberta-small",
                "klue/roberta-base",
                "klue/roberta-large",
            ],
            "electra": [
                "monologg/koelectra-base-v3-discriminator",
                "monologg/koelectra-base-finetuned-sentiment",
            ],
            "roberta": [
                "sentence-transformers/roberta-base-nli-stsb-mean-tokens",
                "jhgan/ko-sroberta-multitask",
            ],
        }

        if model_name in model_list["bert"]:
            self.tokenizer = transformers.BertTokenizer.from_pretrained(self.model_name)
        elif model_name in model_list["electra"]:
            self.tokenizer = transformers.ElectraTokenizer.from_pretrained(self.model_name)
        elif model_name in model_list["roberta"]:
            self.tokenizer = transformers.RobertaTokenizer.from_pretrained(self.model_name)
        else:
            self.tokenizer = transformers.AutoTokenizer.from_pretrained(self.model_name)

        self.tokenizer.model_max_length = 128
        # ###
        # self.add_token = ["<PERSON>"]  # , "rtt", "sampled"
        # ###
        # 넣을 토큰 지정 , "rtt", "sampled"
        self.add_token = [
            "<PERSON>",
            # "...",
            # "!!!",
            # "???",
            # "ㅎㅎㅎ",
            # "ㅋㅋㅋ",
            # "ㄷㄷㄷ",
        ]

        self.new_token_count = self.tokenizer.add_tokens(self.add_token)  # 새롭게 추가된 토큰의 수 저장
        self.swap = swap

        self.target_columns = ["label"]
        self.delete_columns = ["id"]
        self.text_columns = ["sentence_1", "sentence_2"]

    def tokenizing(self, dataframe, swap):
        data = []
        for idx, item in tqdm(dataframe.iterrows(), desc="tokenizing", total=len(dataframe)):
            text = "[SEP]".join([item[text_column] for text_column in self.text_columns])
            text = text_preprocessing(text)  # 전처리 추가

            ### rtt, sampled 토큰을 추가한 경우 텍스트 맨 앞에 해당 토큰 붙여줌
            # source = item["source"].split("-")[-1]
            # text = source + "[SEP]" + text
            ###
            outputs = self.tokenizer(text, add_special_tokens=True, padding="max_length", truncation=True)
            data.append(outputs["input_ids"])

        if swap:  # swap 적용시 양방향 될 수 있도록
            for idx, item in tqdm(dataframe.iterrows(), desc="tokenizing", total=len(dataframe)):
                text = "[SEP]".join([item[text_column] for text_column in self.text_columns[::-1]])
                text = text_preprocessing(text)  # 전처리 추가
                ###
                # source = item["source"].split("-")[-1]
                # text = source + "[SEP]" + text
                ###
                outputs = self.tokenizer(text, add_special_tokens=True, padding="max_length", truncation=True)
                data.append(outputs["input_ids"])

        return data

    def preprocessing(self, data, swap):
        data = data.drop(columns=self.delete_columns)  # id column 삭제

        try:
            if swap:
                targets = data[self.target_columns].values.tolist() + data[self.target_columns].values.tolist()
            else:
                targets = data[self.target_columns].values.tolist()
        except:
            targets = []
        inputs = self.tokenizing(data, swap)

        return inputs, targets

    def setup(self, stage="fit"):
        if stage == "fit":
            total_data = pd.read_csv(self.train_path)

            split = StratifiedShuffleSplit(n_splits=1, test_size=1 - self.train_ratio, random_state=1004)  # 층화 추출 fix
            for train_idx, val_idx in split.split(total_data, total_data["binary-label"]):
                train_data = total_data.loc[train_idx]
                val_data = total_data.loc[val_idx]

            # train_data = total_data.sample(frac=self.train_ratio)
            # val_data = total_data.drop(train_data.index)

            train_inputs, train_targets = self.preprocessing(train_data, self.swap)
            val_inputs, val_targets = self.preprocessing(val_data, self.swap)
            print("train data len : ", len(train_inputs))
            print("valid data len : ", len(val_inputs))

            self.train_dataset = Dataset(train_inputs, train_targets)
            self.val_dataset = Dataset(val_inputs, val_targets)

        else:
            test_data = pd.read_csv(self.test_path)
            predict_data = pd.read_csv(self.predict_path)

            test_inputs, test_targets = self.preprocessing(test_data, False)
            predict_inputs, predict_targets = self.preprocessing(predict_data, False)

            self.test_dataset = Dataset(test_inputs, test_targets)
            self.predict_dataset = Dataset(predict_inputs, predict_targets)

    def train_dataloader(self):
        return torch.utils.data.DataLoader(self.train_dataset, batch_size=self.batch_size, shuffle=self.shuffle)

    def val_dataloader(self):
        return torch.utils.data.DataLoader(self.val_dataset, batch_size=self.batch_size)

    def test_dataloader(self):
        return torch.utils.data.DataLoader(self.test_dataset, batch_size=self.batch_size)

    def predict_dataloader(self):
        return torch.utils.data.DataLoader(self.predict_dataset, batch_size=self.batch_size)

    def new_vocab_size(self):
        return self.new_token_count + self.tokenizer.vocab_size


class KfoldDataloader(pl.LightningDataModule):
    def __init__(
        self,
        model_name,
        batch_size,
        shuffle,
        k,
        num_splits,
        train_path,
        test_path,
        predict_path,
        use_swap,
    ):
        super().__init__()
        self.model_name = model_name
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.k = k
        self.num_splits = num_splits
        self.split_seed = 12345

        self.train_path = train_path
        self.test_path = test_path
        self.predict_path = predict_path

        self.train_dataset = None
        self.val_dataset = None
        self.test_dataset = None
        self.predict_dataset = None

        ## 손으로 수정하는 부분 좀 줄일 수 있게끔 수정
        model_list = {
            "bert": [
                "klue/roberta-small",
                "klue/roberta-base",
                "klue/roberta-large",
            ],
            "electra": [
                "monologg/koelectra-base-v3-discriminator",
                "monologg/koelectra-base-finetuned-sentiment",
            ],
            "roberta": [
                "sentence-transformers/roberta-base-nli-stsb-mean-tokens",
                "jhgan/ko-sroberta-multitask",
            ],
        }

        if model_name in model_list["bert"]:
            self.tokenizer = transformers.BertTokenizer.from_pretrained(self.model_name)
        elif model_name in model_list["electra"]:
            self.tokenizer = transformers.ElectraTokenizer.from_pretrained(self.model_name)
        elif model_name in model_list["roberta"]:
            self.tokenizer = transformers.RobertaTokenizer.from_pretrained(self.model_name)
        else:
            self.tokenizer = transformers.AutoTokenizer.from_pretrained(self.model_name)

        self.tokenizer.model_max_length = 128
        # ###
        # self.add_token = ["<PERSON>"]  # , "rtt", "sampled"
        # ###
        # 넣을 토큰 지정 , "rtt", "sampled"
        self.add_token = [
            "<PERSON>",
            "...",
            "!!!",
            "???",
            "ㅎㅎㅎ",
            "ㅋㅋㅋ",
            "ㄷㄷㄷ",
        ]
        self.new_token_count = self.tokenizer.add_tokens(self.add_token)

        self.swap = use_swap

        self.target_columns = ["label"]
        self.delete_columns = ["id"]
        self.text_columns = ["sentence_1", "sentence_2"]

    def tokenizing(self, dataframe, swap):
        data = []
        for idx, item in tqdm(dataframe.iterrows(), desc="tokenizing", total=len(dataframe)):
            text = "[SEP]".join([item[text_column] for text_column in self.text_columns])
            text = text_preprocessing(text)  # 전처리 추가
            ### rtt, sampled 토큰을 추가한 경우 텍스트 맨 앞에 해당 토큰 붙여줌
            # source = item["source"].split("-")[-1]
            # text = source + "[SEP]" + text
            ###
            outputs = self.tokenizer(text, add_special_tokens=True, padding="max_length", truncation=True)
            data.append(outputs["input_ids"])

        if swap:  # swap 적용시 양방향 될 수 있도록
            for idx, item in tqdm(dataframe.iterrows(), desc="tokenizing", total=len(dataframe)):
                text = "[SEP]".join([item[text_column] for text_column in self.text_columns[::-1]])
                text = text_preprocessing(text)  # 전처리 추가
                ###
                # source = item["source"].split("-")[-1]
                # text = source + "[SEP]" + text
                ###
                outputs = self.tokenizer(text, add_special_tokens=True, padding="max_length", truncation=True)
                data.append(outputs["input_ids"])

        return data

    def preprocessing(self, data, swap):
        data = data.drop(columns=self.delete_columns)

        try:
            if swap:
                targets = data[self.target_columns].values.tolist() + data[self.target_columns].values.tolist()
            else:
                targets = data[self.target_columns].values.tolist()
        except:
            targets = []
        inputs = self.tokenizing(data, swap)

        return inputs, targets

    def setup(self, stage="fit"):
        if stage == "fit":
            total_data = pd.read_csv(self.train_path)
            total_inputs, total_targets = self.preprocessing(total_data, self.swap)
            total_dataset = Dataset(total_inputs, total_targets)

            kf = KFold(
                n_splits=self.num_splits,
                shuffle=self.shuffle,
                random_state=self.split_seed,
            )
            all_splits = [k for k in kf.split(total_dataset)]

            train_indexes, val_indexes = all_splits[self.k]
            train_indexes, val_indexes = train_indexes.tolist(), val_indexes.tolist()

            self.train_dataset = [total_dataset[x] for x in train_indexes]
            self.val_dataset = [total_dataset[x] for x in val_indexes]

        else:
            test_data = pd.read_csv(self.test_path)
            predict_data = pd.read_csv(self.predict_path)

            test_inputs, test_targets = self.preprocessing(test_data, False)
            predict_inputs, predict_targets = self.preprocessing(predict_data, False)

            self.test_dataset = Dataset(test_inputs, test_targets)
            self.predict_dataset = Dataset(predict_inputs, predict_targets)

    def train_dataloader(self):
        return torch.utils.data.DataLoader(self.train_dataset, batch_size=self.batch_size, shuffle=self.shuffle)

    def val_dataloader(self):
        return torch.utils.data.DataLoader(self.val_dataset, batch_size=self.batch_size)

    def test_dataloader(self):
        return torch.utils.data.DataLoader(self.test_dataset, batch_size=self.batch_size)

    def predict_dataloader(self):
        return torch.utils.data.DataLoader(self.predict_dataset, batch_size=self.batch_size)

    def new_vocab_size(self):
        return self.new_token_count + self.tokenizer.vocab_size


def text_preprocessing(sentence):
    s = re.sub(r"!!+", "!!!", sentence)  # !한개 이상 -> !!! 고정
    s = re.sub(r"\?\?+", "???", s)  # ?한개 이상 -> ??? 고정
    s = re.sub(r"\.\.+", "...", s)  # .두개 이상 -> ... 고정
    s = re.sub(r"\~+", "~", s)  # ~한개 이상 -> ~ 고정
    s = re.sub(r"\;+", ";", s)  # ;한개 이상 -> ; 고정
    s = re.sub(r"ㅎㅎ+", "ㅎㅎㅎ", s)  # ㅎ두개 이상 -> ㅎㅎㅎ 고정
    s = re.sub(r"ㅋㅋ+", "ㅋㅋㅋ", s)  # ㅋ두개 이상 -> ㅋㅋㅋ 고정
    s = re.sub(r"ㄷㄷ+", "ㄷㄷㄷ", s)  # ㄷ두개 이상 -> ㄷㄷㄷ 고정
    return s
