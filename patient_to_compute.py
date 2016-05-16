#!/usr/bin/env python

import private_cloud;
import amazon;
import ccc_model_common;
import argparse;
import sys;
import math;
import json;
from collections import OrderedDict

def determine_cores_and_storage(patients_stats_dict, operating_period_in_years=3):
    num_samples_per_year = patients_stats_dict['num_patients_per_year']*patients_stats_dict['num_samples_per_patient_per_year'];
    total_num_samples = num_samples_per_year*operating_period_in_years;
    total_usable_storage = total_num_samples*patients_stats_dict['storage_per_sample'];
    num_samples_per_day = float(num_samples_per_year)/365;
    num_cores = int(math.ceil(num_samples_per_day/patients_stats_dict['num_samples_processed_per_core_per_day']));
    return (num_cores, total_usable_storage);

def modify_cost_dict(cost_dict, name, config_dict, params):
        summary_dict = OrderedDict();
        summary_dict['num_patients_per_year'] = config_dict['num_patients_per_year'];
        summary_dict['num_samples_per_patient_per_year'] = config_dict['num_samples_per_patient_per_year'];
        for key,value in params.iteritems():
            summary_dict[key] = value;
        for key, value in cost_dict['summary'].iteritems():
            summary_dict[key] = value;
        cost_dict['name'] = name;
        cost_dict['summary'] = summary_dict;

def main():
    parser = argparse.ArgumentParser(description='Patients to compute calculator');
    required_named_args_group = parser.add_argument_group('Required named arguments');
    required_named_args_group.add_argument('--patients_file', help='JSON file containing patients stats', required=True);
    required_named_args_group.add_argument('--pvt_cloud_model_parameters_file', help='Path to cloud model parameters file', required=True);
    required_named_args_group.add_argument('--aws_model_parameters_file', help='Path to cloud model parameters file', required=True);
    required_named_args_group.add_argument('--ec2_pricing_json_file', help='Path to AWS EC2 pricing JSON file', required=True);
    required_named_args_group.add_argument('--memory_per_core', help='Memory/RAM (in GB) per core', required=True, type=int);
    required_named_args_group.add_argument('--bandwidth', '-b', help='External bandwidth (in Mbps)', required=True, type=int);
    required_named_args_group.add_argument('--bandwidth_utilization', help='Percentage of external bandwidth used', required=True, type=float);
    parser.add_argument('--operating_period', help='Operating period in years - default: 3 years', default=3, type=int);
    parser.add_argument('--include_IT_cost', help='Include IT cost (default: False)', action='store_true');
    parser.add_argument('--aws_support', choices=['business', 'enterprise'], default=None);
    arguments = parser.parse_args();
    patients_dict = ccc_model_common.parse_model_params_file(arguments.patients_file);
    pvt_cloud_model = ccc_model_common.parse_model_params_file(arguments.pvt_cloud_model_parameters_file);
    aws_model = ccc_model_common.parse_model_params_file(arguments.aws_model_parameters_file);
    ec2_pricing_dict = ccc_model_common.parse_model_params_file(arguments.ec2_pricing_json_file);
    pvt_cost_dict_list = [];
    aws_cost_dict_list = [];
    config_idx = 0;
    for config in patients_dict['configurations']:
        config_name = config['name'] if ('name' in config) else str(config_idx);
        num_cores, usable_storage = determine_cores_and_storage(config, arguments.operating_period);
        storage = ccc_model_common.determine_raw_storage(pvt_cloud_model, usable_storage);
        pvt_config = private_cloud.PrivateCloudArgumentsHandler(model_parameters_dict=pvt_cloud_model, num_cores=num_cores,
                memory_per_core=arguments.memory_per_core, storage=storage, bandwidth=arguments.bandwidth,
                bandwidth_utilization=arguments.bandwidth_utilization, include_IT_cost=arguments.include_IT_cost,
                operating_period_in_years=arguments.operating_period);
        cost_dict = private_cloud.compute_tco(pvt_config, do_print=False);
        modify_cost_dict(cost_dict, config_name, config, OrderedDict([('num_cores', num_cores), ('raw_storage_in_TB', storage),
            ('usable_storage_in_TB', usable_storage)]));
        pvt_cost_dict_list.append(cost_dict);
        aws_config = amazon.AmazonArgumentsHandler(model_parameters_dict=aws_model, ec2_pricing_dict=ec2_pricing_dict,
                num_cores=num_cores, memory_per_core=arguments.memory_per_core, storage=storage, bandwidth=arguments.bandwidth,
                bandwidth_utilization=arguments.bandwidth_utilization, aws_support=arguments.aws_support);
        cost_dict = amazon.compute_tco(aws_config, do_print=False);
        modify_cost_dict(cost_dict, config_name, config, OrderedDict([('num_cores', num_cores), ('raw_storage_in_TB', storage),
            ('usable_storage_in_TB', usable_storage) ]));
        aws_cost_dict_list.append(cost_dict);
        config_idx += 1;
    complete_dict = OrderedDict();
    complete_dict['private_cloud'] = pvt_cost_dict_list;
    complete_dict['AWS'] = aws_cost_dict_list;
    print(json.dumps(complete_dict, indent=4, separators=(',', ': ')));
    sys.stdout.write('Private cloud');
    ccc_model_common.print_cost_summary_csv(pvt_cost_dict_list);
    sys.stdout.write('\nAWS');
    ccc_model_common.print_cost_summary_csv(aws_cost_dict_list);
if __name__ == "__main__":
    main()
