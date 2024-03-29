# Copyright 2021 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""edsr train script"""
import os
from mindspore import context
from mindspore import dataset as ds
import mindspore.nn as nn
from mindspore.context import ParallelMode
from mindspore.train.serialization import load_checkpoint, load_param_into_net
from mindspore.communication.management import init
from mindspore.train.callback import ModelCheckpoint, CheckpointConfig, LossMonitor, TimeMonitor
from mindspore.common import set_seed
from mindspore.train.model import Model
from src.args import args
from src.data.div2k import DIV2K
from src.model import EDSR

def train_net():
    """train edsr"""
    set_seed(1)
    device_id = int(os.getenv('DEVICE_ID', '0'))
    rank_id = int(os.getenv('RANK_ID', '0'))
    device_num = int(os.getenv('RANK_SIZE', '1'))
    # if distribute:
    if device_num > 1:
        init()
        context.set_auto_parallel_context(parallel_mode=ParallelMode.DATA_PARALLEL,
                                          device_num=device_num, gradients_mean=True)
    context.set_context(mode=context.GRAPH_MODE, device_target="Ascend", save_graphs=False, device_id=device_id)
    train_dataset = DIV2K(args, name=args.data_train, train=True, benchmark=False)
    train_dataset.set_scale(args.task_id)
    train_de_dataset = ds.GeneratorDataset(train_dataset, ["LR", "HR"], num_shards=device_num,
                                           shard_id=rank_id, shuffle=True)
    train_de_dataset = train_de_dataset.batch(args.batch_size, drop_remainder=True)
    net_m = EDSR(args)
    print("Init net successfully")
    if args.ckpt_path:
        param_dict = load_checkpoint(args.ckpt_path)
        load_param_into_net(net_m, param_dict)
        print("Load net weight successfully")
    step_size = train_de_dataset.get_dataset_size()
    lr = []
    for i in range(0, args.epochs):
        cur_lr = args.lr / (2 ** ((i + 1)//200))
        lr.extend([cur_lr] * step_size)
    opt = nn.Adam(net_m.trainable_params(), learning_rate=lr, loss_scale=args.loss_scale)
    loss = nn.L1Loss()
    model = Model(net_m, loss_fn=loss, optimizer=opt)
    time_cb = TimeMonitor(data_size=step_size)
    loss_cb = LossMonitor()
    cb = [time_cb, loss_cb]
    config_ck = CheckpointConfig(save_checkpoint_steps=args.ckpt_save_interval * step_size,
                                 keep_checkpoint_max=args.ckpt_save_max)
    ckpt_cb = ModelCheckpoint(prefix="edsr", directory=args.ckpt_save_path, config=config_ck)
    if device_id == 0:
        cb += [ckpt_cb]
    model.train(args.epochs, train_de_dataset, callbacks=cb, dataset_sink_mode=True)


if __name__ == "__main__":
    train_net()
