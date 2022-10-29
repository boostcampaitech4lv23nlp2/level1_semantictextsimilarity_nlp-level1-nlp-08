import argparse
import random

import numpy as np
import pandas as pd
import pytorch_lightning as pl
import torch

import inference
import train

from omegaconf import OmegaConf

# fix random seeds for reproducibility

if __name__ == "__main__":
    # 하이퍼 파라미터 등 각종 설정값을 입력받습니다
    # 터미널 실행 예시 : python3 run.py --batch_size=64 ...
    # 실행 시 '--batch_size=64' 같은 인자를 입력하지 않으면 default 값이 기본으로 실행됩니다
    parser = argparse.ArgumentParser()

    parser.add_argument("--config", "-c", type=str, default="pjh")
    parser.add_argument("--mode", "-m", required=True)
    parser.add_argument(
        "--saved_model",
        "-s",
        default="save_models/model.pt",
        help="저장된 모델의 파일 경로를 입력해주세요. 예시: save_models/klue/roberta-small/epoch=?-step=?.ckpt 또는 save_models/model.pt",
    )
    args, _ = parser.parse_known_args()
    conf = OmegaConf.load(f"./config/{args.config}.yaml")

    SEED = conf.utils.seed
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True)

    if args.mode == "train" or args.mode == "t":
        # num_folds 변수 확인
        if conf.k_fold.use_k_fold:
            train.k_train(conf)
        else:
            train.train(conf)

    elif args.mode == "continue train" or args.mode == "ct":
        train.continue_train(args, conf)

    elif args.mode == "exp" or args.mode == "e":
        exp_count = int(input("실험할 횟수를 입력해주세요 "))
        train.sweep(conf, exp_count)

    elif args.mode == "inference" or args.mode == "i":
        inference.inference(args, conf)
    else:
        print("모드를 다시 설정해주세요 ")
        print("train     : t,\ttrain")
        print("exp       : e,\texp")
        print("inference : i,\tinference")
