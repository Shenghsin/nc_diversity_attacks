# PGD + Diversity Regularization on MNIST

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

import torchvision
import torchvision.transforms as transforms
from torchvision.datasets import DatasetFolder, ImageFolder

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

random_seed = 1
torch.manual_seed(random_seed)

data_dir = r'C:\data\udacity_self_driving_car'
targets_file = 'targets.csv'
batch_size = 32

dataset = car_loader(target_csv_file=os.path.join(data_dir, targets_file),
                    img_dir=os.path.join(data_dir, 'data'),
                    device=device,
                    num_classes=25,
                    transform=transforms.Compose([transforms.ToTensor(),
                                                  transforms.ToPILImage(),
                                                  transforms.Resize((100,100)),
                                                  transforms.ToTensor()]))

test_loader = DataLoader(dataset, batch_size=batch_size)

# Generate a custom batch to ensure that each "class" of steering angles is equally represented
num_per_class = 4
class_distribution = torch.ones(dataset.num_classes) * num_per_class
inputs, targets, classes = generate_batch_reg(dataset, class_distribution, device)

# # Load Pretrained Models if available

## Dave_orig
dave_o = Dave_orig().to(device)
dave_o = get_pretrained_weights(dave_o, 'pretrained_models/driving/') 

## Dave_norminit
dave_n = Dave_norminit().to(device)
dave_n = get_pretrained_weights(dave_n, 'pretrained_models/driving/') 

# # Attack Time
def main():

    models = [dave_o, dave_n]

    # attack params
    epsilon = 100.
    num_steps = 20
    step_size = 0.01
    log_frequency = 100

    # primary evaluation criteria
    attack_versions = [cw_div_reg_attack]
    reg_weights = [0, 1, 10, 100, 1000, 10000, 100000, 1000000]
    confidences = [0, 20, 40]

    # neuron coverage params
    nc_threshold = 0. # all activations are scaled to (0,1) after relu

    # inception score (is) params
    is_cuda = use_cuda
    is_batch_size = 10
    is_resize = True
    is_splits = 10

    # frechet inception distance score (fid) params
    real_path = "C:/temp_imgs/mnist/real_pgd_driving/"
    fake_path = "C:/temp_imgs/mnist/fake_pgd_driving/"
    fid_batch_size = 64
    fid_cuda = use_cuda                   

    with open('logs/pgd_mnist_error_log_2020.02.10.txt', 'w') as error_log: 

        for model in models:

            results = []
            model_name = model.__class__.__name__
            save_file_path = "assets/pgd_results_driving_" + model_name + "_2020.02.10.pkl"   

            # neuron coverage
            covered_neurons, total_neurons, neuron_coverage_000 = eval_nc(model, inputs, 0.00)
            print('neuron_coverage_000:', neuron_coverage_000)
            covered_neurons, total_neurons, neuron_coverage_020 = eval_nc(model, inputs, 0.20)
            print('neuron_coverage_020:', neuron_coverage_020)
            covered_neurons, total_neurons, neuron_coverage_050 = eval_nc(model, inputs, 0.50)
            print('neuron_coverage_050:', neuron_coverage_050)
            covered_neurons, total_neurons, neuron_coverage_075 = eval_nc(model, inputs, 0.75)
            print('neuron_coverage_075:', neuron_coverage_075)

            init = {'desc': 'Initial inputs, targets, classes', 
                    'inputs': inputs,
                    'targets': targets,
                    'classes': classes,
                    'neuron_coverage_000': neuron_coverage_000,
                    'neuron_coverage_020': neuron_coverage_020,
                    'neuron_coverage_050': neuron_coverage_050,
                    'neuron_coverage_075': neuron_coverage_075}
            
            results.append(init) 

            n=2 # skip relu layers
            layer_dict = get_model_modules(model)
            target_layers = list(layer_dict)[0::n]

            for attack in attack_versions:
                for layer_idx in target_layers:
                    module = layer_dict[layer_idx]
                    for rw in reg_weights:
                        for c in confidences:

                            try:
                            
                                timestamp = str(datetime.datetime.now()).replace(':','.')
                                
                                attack_detail = ['model', model_name,
                                                 'timestamp', timestamp, 
                                                 'attack', attack.__name__, 
                                                 'layer: ', layer_idx, 
                                                 'regularization_weight: ', rw, 
                                                 'confidence: ', c]

                                print(*attack_detail, sep=' ')
     
                                # adversarial attack 
                                adversaries = cw_div_reg_attack(model=model, 
                                                                 modules=module, 
                                                                 regularizer_weight=rw, 
                                                                 inputs=inputs, 
                                                                 targets=targets, 
                                                                 dataset=dataset,
                                                                 device=device, 
                                                                 targeted=False, 
                                                                 norm_type='inf', 
                                                                 epsilon=1.5, 
                                                                 confidence=c, 
                                                                 c_range=(1, 1e10), 
                                                                 search_steps=5, 
                                                                 max_steps=1001, 
                                                                 abort_early=True, 
                                                                 box=(-1., 1.), 
                                                                 optimizer_lr=1e-2, 
                                                                 init_rand=False, 
                                                                 log_frequency=100)
                               
                                # evaluate adversary effectiveness
                                mse, pert_acc, orig_acc = eval_performance_reg(model, inputs, adversaries, targets, classes, dataset)
                                # sample_3D_images_reg(model, inputs, adversaries, targets, classes, dataset)
                                
                                pert_acc = pert_acc.item() / 100.
                                orig_acc = orig_acc.item() / 100.

                                attack_success_rate = 1 - pert_acc
                                
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
                                preprocessed_advs = preprocess_3D_imgs(adversaries)
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

                                # output impoartiality
                                pert_output = model(adversaries)
                                y_pred = discretize(pert_output, dataset.boundaries).view(-1)
                                output_impartiality, y_pred_entropy, max_entropy = calculate_output_impartiality(classes, y_pred)
                                print('output_impartiality:', output_impartiality)
                                
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
                                       'output_impartiality': output_impartiality}
                                
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