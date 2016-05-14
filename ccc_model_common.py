#!/usr/bin/env python

import json
import argparse
import sys

class NoServerConfigurationFound(Exception):

    def __init__(self, value):
        self.value = value;

    def __str__(self):
        return repr(self.value);

def parse_model_params_file(filename):
    fptr = open(filename, 'rb');
    model = json.load(fptr);
    fptr.close();
    return model;

class ArgumentsHandler:

    m_model = None;
    m_num_cores = None;
    m_core_utilization = 100;
    m_memory_per_core = None;
    m_storage = None;
    m_storage_utilization = 100;
    m_backup_percentage_per_month = 5;
    m_iops_per_GB_requested = None;
    m_storage_bandwidth_per_TB_requested = None;
    m_bandwidth = None;
    m_bandwidth_utilization = None;
    m_operating_period_in_years = 3;
    m_include_IT_cost = False;

    def add_optional_arguments(self, parser):
        parser.add_argument('--core_utilization', help='Average utilization per core (as a percentage) - default: 100%%', default=100, type=float);
        parser.add_argument('--operating_period_in_years', help='Operating period in years - default: 3 years', default=3, type=int);
        parser.add_argument('--backup_percentage_per_month', help='Percentage of total data that changes per month - default: 5%%',
                default=5, type=float);
        parser.add_argument('--include_IT_cost', help='Include IT cost (default: False)', action='store_true');

    def add_required_arguments(self, parser):
        required_named_args_group = parser.add_argument_group('Required named arguments');
        required_named_args_group.add_argument('--model_parameters_file', '-m', help='Path to cloud model parameters file', required=True);
        required_named_args_group.add_argument('--num_cores', '-c', help='Number of cores', required=True, type=int);
        required_named_args_group.add_argument('--memory_per_core', help='Memory/RAM (in GB) per core', required=True, type=int);
        required_named_args_group.add_argument('--storage', '-s', help='Storage size (in TB)', required=True, type=int);
        required_named_args_group.add_argument('--bandwidth', '-b', help='External bandwidth (in Mbps)', required=True, type=int);
        required_named_args_group.add_argument('--bandwidth_utilization', help='Percentage of external bandwidth used', required=True, type=float);

    def __init__(self, argparse_obj=None, model_parameters_file=None, model_parameters_dict=None, num_cores=None,
            memory_per_core=None, storage=None, bandwidth=None, bandwidth_utilization=None,
            **kwargs):
        if(argparse_obj):
            self.add_required_arguments(argparse_obj);
            self.add_optional_arguments(argparse_obj);
            arguments = argparse_obj.parse_args();
            self.m_model = parse_model_params_file(arguments.model_parameters_file);
            self.m_num_cores = arguments.num_cores;
            self.m_core_utilization = arguments.core_utilization;
            self.m_memory_per_core = arguments.memory_per_core;
            self.m_storage = arguments.storage;
            self.m_bandwidth = arguments.bandwidth;
            self.m_bandwidth_utilization = arguments.bandwidth_utilization;
            self.m_operating_period_in_years = arguments.operating_period_in_years;
            self.m_backup_percentage_per_month = arguments.backup_percentage_per_month;
            self.m_include_IT_cost = arguments.include_IT_cost;
        else:
            if(model_parameters_dict):
                self.m_model = model_parameters_dict;
            else:
                self.m_model = parse_model_params_file(model_parameters_file);
            self.m_num_cores = num_cores;
            self.m_memory_per_core = memory_per_core;
            self.m_storage = storage;
            self.m_bandwidth = bandwidth;
            self.m_bandwidth_utilization = bandwidth_utilization;
            for k,v in kwargs.iteritems():
                setattr(self, 'm_'+k, v);

def determine_usable_storage(model, raw_storage_size):
    storage_params = model['storage'];
    usable_storage = (float(100-storage_params['os_penalty_percentage'])/100)*raw_storage_size;
    usable_storage = (float(100-storage_params['raid_penalty_percentage'])/100)*usable_storage;
    return usable_storage;

def piecewise_linear_function(model, segment_key, cost_key, value):
    remaining = value;
    last_limit_value = 0;
    total_cost = 0;
    for range_dict in model:
        if(remaining <= 0):
            return total_cost;
        total_cost += min(remaining, range_dict[segment_key]-last_limit_value)*range_dict[cost_key];
        remaining = value - range_dict[segment_key];
        last_limit_value = range_dict[segment_key];
    return total_cost;

def print_cost_summary_csv(cost_dict_list):
    if(len(cost_dict_list) == 0):
        return;
    for cost_dict in cost_dict_list:
        sys.stdout.write(','+cost_dict['name']);
    sys.stdout.write('\n');
    for key in cost_dict_list[0]['summary'].keys():
        sys.stdout.write(key);
        for cost_dict in cost_dict_list:
            sys.stdout.write(','+str(cost_dict['summary'][key]));
        sys.stdout.write('\n');

