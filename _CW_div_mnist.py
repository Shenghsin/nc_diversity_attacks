# CW + Diversity Regularization on MNIST

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

import torchvision
import torchvision.transforms as transforms

import numpy as np
import matplotlib.pyplot as plt

import traceback
import warnings
warnings.filterwarnings('ignore')

import datetime
import glob
import os
import pickle

import pandas as pd

from models import *
from div_attacks import *
from neuron_coverage import *
from inception_score import *
from fid_score import *
from utils import *

# check if CUDA is available
device = torch.device("cpu")
use_cuda = False
if torch.cuda.is_available():
    print('CUDA is available!')
    device = torch.device("cuda")
    use_cuda = True
else:
    print('CUDA is not available.')

n_epochs = 10
learning_rate = 0.01
momentum = 0.5

random_seed = 1
torch.manual_seed(random_seed)

#  torchvision.transforms.Normalize(
#    (0.1307,), (0.3081,))

data_dir = "C:\data\MNIST"
batch_size_train = 64
batch_size_test = 100

train_loader = torch.utils.data.DataLoader(
    torchvision.datasets.MNIST(data_dir, train=True, download=True,
                             transform=torchvision.transforms.Compose([
                               torchvision.transforms.ToTensor()
                             ])),
    batch_size=batch_size_train, shuffle=True, pin_memory=True)

# test_loader = torch.utils.data.DataLoader(
#     torchvision.datasets.MNIST(data_dir, train=False, download=True,
#                          transform=torchvision.transforms.Compose([
#                            torchvision.transforms.ToTensor()
#                          ])),
#     batch_size=batch_size_test, shuffle=False, pin_memory=True)


# inputs, targets = next(iter(test_loader))
# inputs = inputs.to(device)
# targets = targets.to(device)

# Generate a custom batch to ensure that each class is equally represented

num_per_class = 10

dataset = torchvision.datasets.MNIST(root=data_dir, 
                                     train=False, 
                                     download=True,
                                     transform=transforms.Compose([
                                         transforms.ToTensor()
                                     ]))

class_distribution = torch.ones(len(np.unique(dataset.targets))) * num_per_class
inputs, targets = generate_batch(dataset, class_distribution, device)

# # Load Pretrained Models if available

## DenseNet5
fcnet5 = FCNet5().to(device)
fcnet5 = get_pretrained_weights(fcnet5) 

## DenseNet10
fcnet10 = FCNet10().to(device) 
fcnet10 = get_pretrained_weights(fcnet10)

## Conv1DNet
conv1dnet = Conv1DNet().to(device)
conv1dnet = get_pretrained_weights(conv1dnet)

## Conv2DNet
conv2dnet = Conv2DNet().to(device)
conv2dnet = get_pretrained_weights(conv2dnet)

# # Attack Time
def main():

    models = [fcnet5, fcnet10, conv1dnet, conv2dnet]

    # attack params
    search_steps=5
    targeted=False
    norm_type='inf'
    epsilon=100.
    c_range=(1e-3, 1e10)
    max_steps=1000
    abort_early=True
    optimizer_lr=5e-4
    init_rand=False
    log_frequency = 100

    mean = (0.1307,) # the mean used in inputs normalization
    std = (0.3081,) # the standard deviation used in inputs normalization
    box = (min((0 - m) / s for m, s in zip(mean, std)),
           max((1 - m) / s for m, s in zip(mean, std)))

    attack_versions = [cw_div4_attack] # [cw_div1_attack, cw_div2_attack, cw_div3_attack, cw_div4_attack]
    reg_weights = [0, 1, 10, 100, 1000, 10000, 100000, 1000000]
    confidences = [0, 20, 40]

    # neuron coverage params
    nc_threshold = 0. # all activations are scaled to (0,1) after relu

    # inception score (is) params
    is_cuda = use_cuda
    is_batch_size = 10
    is_resize = True
    is_splits = 10

    # fréchet inception distance score (fid) params
    real_path = "C:/temp_imgs/mnist/real_cw_mnist/"
    fake_path = "C:/temp_imgs/mnist/fake_cw_mnist/"
    fid_batch_size = 64
    fid_cuda = use_cuda                      

    with open('logs/cw_mnist_error_log_2019.10.15.txt', 'w') as error_log: 

        for model in models:

            for attack in attack_versions:

                results = []
                model_name = model.__class__.__name__
                save_file_path = "assets/cw_results_mnist_" + model_name + "_2019.10.15.pkl"   

                init = {'desc': 'Initial inputs and targets', 
                        'inputs': inputs, 
                        'targets': targets}
                
                results.append(init) 

                n=2 # skip relu layers
                layer_dict = get_model_modules(model)
                target_layers = list(layer_dict)[0::n]

                for layer_idx in target_layers:
                    module = layer_dict[layer_idx]
                    for rw in reg_weights:
                        for c in confidences:

                            try:
                            
                                timestamp = str(datetime.datetime.now()).replace(':','.')
                                
                                attack_detail = ['timestamp', timestamp, 
                                                 'attack', attack.__name__, 
                                                 'layer: ', layer_idx, 
                                                 'regularization_weight: ', rw, 
                                                 'confidence: ', c]

                                print(*attack_detail, sep=' ')
     
                                # adversarial attack 
                                adversaries = attack(model, module, rw, inputs, targets, device, targeted, norm_type, epsilon,
                                                     c, c_range, search_steps, max_steps, abort_early, box,
                                                     optimizer_lr, init_rand, log_frequency)
                               
                                # evaluate adversary effectiveness
                                pert_acc, orig_acc = eval_performance(model, inputs, adversaries, targets)
                                # sample_1D_images(model, inputs, adversaries, targets)
                                
                                pert_acc = pert_acc.item() / 100.
                                orig_acc = orig_acc.item() / 100.
                                
                                # neuron coverage
                                covered_neurons, total_neurons, neuron_coverage_000 = eval_nc(model, adversaries, 0.00)
                                print('neuron_coverage_000:', neuron_coverage_000)
                                covered_neurons, total_neurons, neuron_coverage_020 = eval_nc(model, adversaries, 0.20)
                                print('neuron_coverage_020:', neuron_coverage_020)
                                covered_neurons, total_neurons, neuron_coverage_050 = eval_nc(model, adversaries, 0.50)
                                print('neuron_coverage_050:', neuron_coverage_050)
                                covered_neurons, total_neurons, neuron_coverage_075 = eval_nc(model, adversaries, 0.75)
                                print('neuron_coverage_075:', neuron_coverage_075)
                                
                                # inception score
                                preprocessed_advs = preprocess_1D_imgs(adversaries)
                                mean_is, std_is = inception_score(preprocessed_advs, is_cuda, is_batch_size, is_resize, is_splits)
                                print('inception_score:', mean_is)
                                
                                # fid score 
                                paths = [real_path, fake_path]
                                
                                # dimensionality = 64
                                target_num = 64
                                generate_imgs(inputs, real_path, target_num)
                                generate_imgs(adversaries, fake_path, target_num)
                                fid_score_64 = calculate_fid_given_paths(paths, fid_batch_size, fid_cuda, dims=64)
                                print('fid_score_64:', fid_score_64)
                                
                                # dimensionality = 2048
                                target_num = 2048
                                generate_imgs(inputs, real_path, target_num)
                                generate_imgs(adversaries, fake_path, target_num)
                                fid_score_2048 = calculate_fid_given_paths(paths, fid_batch_size, fid_cuda, dims=2048)
                                print('fid_score_2048:', fid_score_2048)

                                # output bias
                                pert_output = model(adversaries)
                                y_pred = discretize(pert_output, dataset.boundaries).view(-1)

                                output_bias, y_pred_entropy, max_entropy = calculate_output_bias(classes, y_pred)
                                
                                out = {'timestamp': timestamp, 
                                       'attack': attack.__name__,
                                       'model': model_name, 
                                       'layer': layer_idx, 
                                       'regularization_weight': rw, 
                                       'confidence': c, 
                                       'adversaries': adversaries,
                                       'pert_acc':pert_acc, 
                                       'orig_acc': orig_acc,
                                       'attack_success_rate': attack_success_rate, 
                                       'neuron_coverage_000': neuron_coverage_000,
                                       'neuron_coverage_020': neuron_coverage_020,
                                       'neuron_coverage_050': neuron_coverage_050,
                                       'neuron_coverage_075': neuron_coverage_075,
                                       'inception_score': mean_is,
                                       'fid_score_64': fid_score_64,
                                       'fid_score_2048': fid_score_2048,
                                       'output_bias': output_bias}
                                
                                results.append(out)

                                # save incremental outputs
                                with open(save_file_path, 'wb') as handle:
                                    pickle.dump(results, handle, protocol=pickle.HIGHEST_PROTOCOL)

                            except Exception as e: 

                                print(str(traceback.format_exc()))
                                error_log.write("Failed on attack_detail {0}: {1}\n".format(str(attack_detail), str(traceback.format_exc())))

                            finally:

                                pass

if __name__ == '__main__':
    try:
        main()
    except Exception as e: 
        print(traceback.format_exc())