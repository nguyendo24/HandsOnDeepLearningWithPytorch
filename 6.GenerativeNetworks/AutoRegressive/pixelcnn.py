import os
import time
import sys

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn, optim, cuda, backends
from torch.utils import data
from torchvision import datasets, transforms, utils
from flashlight import FlashLight
backends.cudnn.benchmark = True

CUDA = torch.cuda.is_available()

class MaskedConv2d(nn.Conv2d):
    def __init__(self, mask_type, *args, **kwargs):
        super(MaskedConv2d, self).__init__(*args, **kwargs)
        assert mask_type in ('A', 'B')
        self.register_buffer('mask', self.weight.data.clone())
        _, _, kH, kW = self.weight.size()
        self.mask.fill_(1)
        self.mask[:, :, kH // 2, kW // 2 + (mask_type == 'B'):] = 0
        self.mask[:, :, kH // 2 + 1:] = 0

    def forward(self, x):
        self.weight.data *= self.mask
        return super(MaskedConv2d, self).forward(x)

fm = 64
net = nn.Sequential(
    MaskedConv2d('A', 1,  fm, 7, 1, 3, bias=False), nn.BatchNorm2d(fm), nn.ReLU(True),
    MaskedConv2d('B', fm, fm, 7, 1, 3, bias=False), nn.BatchNorm2d(fm), nn.ReLU(True),
    MaskedConv2d('B', fm, fm, 7, 1, 3, bias=False), nn.BatchNorm2d(fm), nn.ReLU(True),
    MaskedConv2d('B', fm, fm, 7, 1, 3, bias=False), nn.BatchNorm2d(fm), nn.ReLU(True),
    MaskedConv2d('B', fm, fm, 7, 1, 3, bias=False), nn.BatchNorm2d(fm), nn.ReLU(True),
    MaskedConv2d('B', fm, fm, 7, 1, 3, bias=False), nn.BatchNorm2d(fm), nn.ReLU(True),
    MaskedConv2d('B', fm, fm, 7, 1, 3, bias=False), nn.BatchNorm2d(fm), nn.ReLU(True),
    MaskedConv2d('B', fm, fm, 7, 1, 3, bias=False), nn.BatchNorm2d(fm), nn.ReLU(True),
    nn.Conv2d(fm, 256, 1))
print(net)
if CUDA:
    net.cuda()

tr = data.DataLoader(datasets.MNIST('data', train=True, download=True, transform=transforms.ToTensor()),
                     batch_size=128, shuffle=True, num_workers=1, pin_memory=True)
te = data.DataLoader(datasets.MNIST('data', train=False, download=True, transform=transforms.ToTensor()),
                     batch_size=128, shuffle=False, num_workers=1, pin_memory=True)
if CUDA:
    sample = torch.Tensor(144, 1, 28, 28).cuda()
else:
    sample = torch.Tensor(144, 1, 28, 28)
optimizer = optim.Adam(net.parameters())
for epoch in range(25):
    # train
    err_tr = []
#     cuda.synchronize()
    time_tr = time.time()
    net.train(True)
    fl = FlashLight(net)
    for input, _ in tr:
        if CUDA:
            input = input.cuda(async=True)
        target = (input.data[:,0] * 255).long()
        loss = F.cross_entropy(net(input), target)
        print(loss.item())
        err_tr.append(loss.item())
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    # cuda.synchronize()
    time_tr = time.time() - time_tr

    # compute error on test set
    err_te = []
    # cuda.synchronize()
    time_te = time.time()
    net.train(False)
    for input, _ in te:
        if CUDA:
            input = input.cuda(async=True)
        target = (input.data[:,0] * 255).long()
        loss = F.cross_entropy(net(input), target)
        err_te.append(loss.data[0])
    # cuda.synchronize()
    time_te = time.time() - time_te

    # sample
    sample.fill_(0)
    net.train(False)
    for i in range(28):
        for j in range(28):
            out = net(sample, volatile=True)
            probs = F.softmax(out[:, :, i, j]).data
            sample[:, :, i, j] = torch.multinomial(probs, 1).float() / 255.
    utils.save_image(sample, 'sample_{:02d}.png'.format(epoch), nrow=12, padding=0)

    print('epoch={}; nll_tr={:.7f}; nll_te={:.7f}; time_tr={:.1f}s; time_te={:.1f}s'.format(
        epoch, np.mean(err_tr), np.mean(err_te), time_tr, time_te))
