#!/usr/bin/env python

import sys
import json
import argparse
import math
from collections import OrderedDict
from ccc_model_common import ArgumentsHandler
from ccc_model_common import NoServerConfigurationFound
from ccc_model_common import piecewise_linear_function
from ccc_model_common import determine_usable_storage

class AmazonArgumentsHandler(ArgumentsHandler):

    m_ec2_pricing_model=None
    m_aws_support=None

    def add_amazon_required_arguments(self, parser):
        required_named_args_group = parser.add_argument_group('Required named arguments for Amazon pricing');
        required_named_args_group.add_argument('--ec2_pricing_json_file', help='Path to AWS EC2 pricing JSON file', required=True);

    def add_amazon_optional_arguments(self, parser):
        parser.add_argument('--include_aws_support', choices=['business', 'enterprise'], default=None);

    def __init__(self, argparse_obj=None, model_parameters_file=None, ec2_pricing_json_file=None, num_cores=None, memory_per_core=None, storage=None,
            bandwidth=None, bandwidth_utilization=None, operating_period_in_years=None):
        
        if(argparse_obj):
            self.add_amazon_required_arguments(argparse_obj);
            self.add_amazon_optional_arguments(argparse_obj);
        ArgumentsHandler.__init__(self, argparse_obj, model_parameters_file, num_cores, memory_per_core, storage,
                bandwidth, bandwidth_utilization, operating_period_in_years);
        if(argparse_obj):
            arguments = argparse_obj.parse_args();
            ec2_pricing_json_file = arguments.ec2_pricing_json_file;
            self.m_aws_support = arguments.include_aws_support;
        fptr = open(ec2_pricing_json_file, 'rb');
        self.m_ec2_pricing_model = json.load(fptr);
        fptr.close();
        product_types = set();
        for product_key,product_info in self.m_ec2_pricing_model['products'].iteritems():
            if('productFamily' in product_info):
                product_types.add(product_info['productFamily']);

def create_instance_to_products_list(model, ec2_pricing_model):
    instances_set = set(model['instances']);
    location = model['location'];
    operating_system = model['operating_system'];
    instance_to_products_list = OrderedDict();
    for product_key, product_info in ec2_pricing_model['products'].iteritems():
        if('productFamily' in product_info and product_info['productFamily'] == 'Compute Instance'):
            instance_type = product_info['attributes']['instanceType'];
            if(instance_type in instances_set and product_info['attributes']['location'] == location and \
                    product_info['attributes']['operatingSystem'] == operating_system):
                if(instance_type not in instance_to_products_list):
                    instance_to_products_list[instance_type] = [];
                instance_to_products_list[instance_type].append(product_info);
    return instance_to_products_list;

def get_num_cores_in_instance(model, instance_to_products_list, instance_type):
    if((instance_type not in instance_to_products_list) or (len(instance_to_products_list[instance_type]) == 0)):
        return None;
    product_info = instance_to_products_list[instance_type][0];
    num_vcpus = int(product_info['attributes']['vcpu']);
    num_cores = int(float(num_vcpus)/model['core_to_vcpu_factor']);
    return num_cores;

def get_memory_in_instance(instance_to_products_list, instance_type):
    if((instance_type not in instance_to_products_list) or (len(instance_to_products_list[instance_type]) == 0)):
        return None;
    product_info = instance_to_products_list[instance_type][0];
    unit_string_to_GiB_convert_factor = { 'GiB':1, 'TiB':1024, 'MiB': 1/1024 };
    tokens = product_info['attributes']['memory'].split();
    memory_in_instance = float(tokens[0])*unit_string_to_GiB_convert_factor[tokens[1]];
    return memory_in_instance;

def is_instance_adequate(model, instance_to_products_list, instance_type, memory_per_core):
    if((instance_type not in instance_to_products_list) or (len(instance_to_products_list[instance_type]) == 0)):
        return False;
    memory_in_instance = get_memory_in_instance(instance_to_products_list, instance_type);
    return (memory_in_instance and memory_in_instance >= memory_per_core);

def determine_num_usable_cores_in_instance_type(model, instance_to_products_list, instance_type, memory_per_core):
    num_cores = get_num_cores_in_instance(model, instance_to_products_list, instance_type);
    memory_in_instance = get_memory_in_instance(instance_to_products_list, instance_type);
    if(num_cores and memory_in_instance):
        num_usable_cores = int(float(memory_in_instance)/memory_per_core);
        return min(num_usable_cores, num_cores);
    else:
        return 0;

def compute_instance_type_cost(model, ec2_pricing_model, instance_to_products_list, instance_type, tenancy, offer_term,
        num_cores, core_utilization, memory_per_core, operating_period_in_years):
    num_usable_cores_per_instance = determine_num_usable_cores_in_instance_type(model, instance_to_products_list, instance_type, memory_per_core);
    if(num_usable_cores_per_instance < 1):
        return None;
    num_instances = int(math.ceil(float(num_cores)/num_usable_cores_per_instance));
    upfront_portion_code = model['offer_term_parameters']['upfront_portion_code']['code'];
    hourly_payment_code = model['offer_term_parameters']['hourly_payment_code']['code'];
    hours_used = operating_period_in_years*365*24;
    if(offer_term  == 'OnDemand'):
        hours_used = float(hours_used*core_utilization)/100; 
    for product_info in instance_to_products_list[instance_type]:
        if(product_info['attributes']['tenancy'] == tenancy):
            sku_code = product_info['sku'];
            terms_dict = None;
            if(offer_term == 'OnDemand'):
                terms_dict = ec2_pricing_model['terms']['OnDemand'];
            else:
                terms_dict = ec2_pricing_model['terms']['Reserved'];
            offer_term_code = model['offer_term_parameters'][offer_term]['code'];
            sku_term_key = sku_code+'.'+offer_term_code;
            if(sku_code in terms_dict and sku_term_key in terms_dict[sku_code]):
                pricing_dict = terms_dict[sku_code][sku_term_key]['priceDimensions'];
                hourly_rate_key = sku_term_key+'.'+hourly_payment_code;
                upfront_rate_key = sku_term_key+'.'+upfront_portion_code;
                if(hourly_rate_key in pricing_dict or upfront_rate_key in pricing_dict):
                    hourly_cost = None;
                    upfront_cost = None;
                    total_cost = 0;
                    if(hourly_rate_key in pricing_dict):
                        hourly_cost = num_instances*float(pricing_dict[hourly_rate_key]['pricePerUnit']['USD'])*hours_used;
                        total_cost += hourly_cost;
                    if(upfront_rate_key in pricing_dict):
                        num_cycles = 1;
                        if('duration' in model['offer_term_parameters'][offer_term]):
                            num_cycles = int(math.ceil(float(operating_period_in_years)/model['offer_term_parameters'][offer_term]['duration']));
                        upfront_cost = num_instances*float(pricing_dict[upfront_rate_key]['pricePerUnit']['USD'])*num_cycles;
                        total_cost += upfront_cost;
                    return OrderedDict([ ('instance_type', instance_type), ('tenancy', tenancy), ('offer_term', offer_term),
                        ('sku', sku_code), ('offer_term_code', offer_term_code),
                        ('num_usable_cores_per_instance', num_usable_cores_per_instance),
                        ('memory', get_memory_in_instance(instance_to_products_list, instance_type)),
                        ('num_instances', num_instances), 
                        ('total_hourly_cost', hourly_cost), ('total_upfront_cost', upfront_cost), ('total_cost', total_cost) ]);
                else:
                    return None
            else:
                return None;
    return None

def select_optimal_server_configuration(model, ec2_pricing_model, num_cores, memory_per_core, operating_period_in_years, core_utilization):
    model = model['compute'];
    instance_to_products_list = create_instance_to_products_list(model, ec2_pricing_model);
    min_cost = 100000000000000;
    min_cost_dict = None
    for instance_type in model['instances']:
        #Instance may not have enough memory
        if(not is_instance_adequate(model, instance_to_products_list, instance_type, memory_per_core)):
            continue;
        for tenancy in model['tenancies']:
            for offer_term in model['offer_terms']:
                curr_cost_params = compute_instance_type_cost(model, ec2_pricing_model, instance_to_products_list, instance_type,
                        tenancy, offer_term, num_cores, core_utilization, memory_per_core, operating_period_in_years);
                if(curr_cost_params and curr_cost_params['total_cost'] < min_cost):
                    min_cost = curr_cost_params['total_cost']
                    min_cost_dict = curr_cost_params;
    if(not min_cost_dict):
        raise NoServerConfigurationFound(('No valid EC2 instance found for specified memory per core value : %d')%(memory_per_core)); 
    cost_dict = min_cost_dict;
    discount_value = 0;
    #apply reserved instance discount
    if(min_cost_dict['offer_term'] != 'OnDemand'):
        discount_value = piecewise_linear_function(model['reserved_discount_tiers'], 'segment_limit', 'rate', min_cost_dict['total_cost']);
    cost_dict['summary'] = OrderedDict();
    cost_dict['summary']['ec2_cost'] = min_cost_dict['total_cost'];
    cost_dict['summary']['ec2_hourly_cost'] = min_cost_dict['total_hourly_cost'];
    cost_dict['summary']['ec2_upfront_cost'] = min_cost_dict['total_upfront_cost'];
    cost_dict['summary']['discount'] = discount_value;
    cost_dict['summary']['total_cost'] = min_cost_dict['total_cost'] - discount_value;
    return cost_dict;
    
def compute_storage_cost(model, raw_storage_size, storage_utilization_percentage, operating_period_in_years, backup_percentage_per_month,
        iops_per_GB_requested=None, bandwidth_per_TB_requested=None):
    min_cost_dict = None;
    min_cost = 100000000000000;
    effective_operating_period_in_months = float(12*operating_period_in_years*storage_utilization_percentage)/100;
    usable_storage = determine_usable_storage(model, raw_storage_size);
    for storage_config in model['storage']['ebs']['pricing_tiers']:
        if((iops_per_GB_requested and 'baseline_iops_per_GB' in storage_config and \
            storage_config['baseline_iops_per_GB'] >= iops_per_GB_requested) or \
            (not iops_per_GB_requested and bandwidth_per_TB_requested and 'baseline_bandwidth_per_TB' in storage_config \
            and storage_config['baseline_bandwidth_per_TB'] >= bandwidth_per_TB_requested) or
            (not iops_per_GB_requested and not bandwidth_per_TB_requested)):
            curr_cost = 0;
            if(iops_per_GB_requested and 'price_per_iops_per_month' in storage_config):
                curr_cost += iops_per_GB_requested*effective_operating_period_in_months* \
                        storage_config['price_per_iops_per_month'];
            curr_cost += usable_storage*1024*storage_config['price_per_GB_per_month']*effective_operating_period_in_months;
            if(curr_cost < min_cost):
                min_cost = curr_cost
                min_cost_dict = OrderedDict([
                    ('ebs_type', storage_config['name']),
                    ('usable_storage', usable_storage),
                    ('ebs_cost', curr_cost)
                    ]);
    if(not min_cost_dict):
        raise NoServerConfigurationFound('Could not find storage type with required specification');
    backup_onetime_cost = usable_storage*model['storage']['snapshot_cost_per_TB'];
    backup_monthly_cost = (12*operating_period_in_years*float(usable_storage*backup_percentage_per_month)/100)*model['storage']['snapshot_cost_per_TB'];
    min_cost_dict['backup_onetime_cost'] = backup_onetime_cost;
    min_cost_dict['backup_monthly_cost'] = backup_monthly_cost;
    min_cost_dict['summary'] = OrderedDict();
    min_cost_dict['summary']['ebs_cost'] = min_cost_dict['ebs_cost'];
    min_cost_dict['summary']['backup_cost'] = backup_onetime_cost + backup_monthly_cost;
    min_cost_dict['summary']['total_cost'] = min_cost_dict['ebs_cost']+min_cost_dict['summary']['backup_cost'];
    return min_cost_dict;

def compute_network_cost(model, bandwidth, bandwidth_utilization, operating_period_in_years):
    cost_dict = OrderedDict();
    #Data transfer/month
    data_transfer_per_month = (float(bandwidth*bandwidth_utilization*30*24*3600)/100)*(float(10**6)/(8*1024**3))* \
            (float(model['network']['percentage_outbound_traffic'])/100);
    per_month_cost = piecewise_linear_function(model['network']['pricing_tiers'], "segment_limit_GB", "cost_per_GB", data_transfer_per_month);
    cost_dict['data_transferred_per_month_in_GB'] = data_transfer_per_month;
    cost_dict['summary'] = OrderedDict();
    cost_dict['summary']['total_cost'] = per_month_cost*12*operating_period_in_years;
    return cost_dict;

def compute_support_cost(model, support_type, total_cost, operating_period_in_years):
    cost_dict = { 'summary': { 'total_cost': 0 } };
    if(support_type and support_type in model['support']):
        monthly_cost = float(total_cost)/(12*operating_period_in_years);
        cost_dict['summary']['total_cost'] = (12*operating_period_in_years)* \
                piecewise_linear_function(model['support'][support_type], 'segment_limit', 'rate', monthly_cost);
    return cost_dict;

def compute_tco(args_handler, do_print=False):
    model = args_handler.m_model;
    ec2_pricing_model = args_handler.m_ec2_pricing_model;
    cost_dict = OrderedDict();
    cost_dict['compute'] = select_optimal_server_configuration(model, ec2_pricing_model, args_handler.m_num_cores, args_handler.m_memory_per_core,
            args_handler.m_operating_period_in_years, args_handler.m_core_utilization);
    cost_dict['storage'] = compute_storage_cost(model, args_handler.m_storage, args_handler.m_storage_utilization,
            args_handler.m_operating_period_in_years, args_handler.m_backup_percentage_per_month,
            args_handler.m_iops_per_GB_requested, args_handler.m_storage_bandwidth_per_TB_requested);
    cost_dict['network'] = compute_network_cost(model, args_handler.m_bandwidth, args_handler.m_bandwidth_utilization,
            args_handler.m_operating_period_in_years);
    total_cost = cost_dict['compute']['summary']['total_cost']+cost_dict['storage']['summary']['total_cost']+ \
            cost_dict['network']['summary']['total_cost'];
    cost_dict['support'] = compute_support_cost(model, args_handler.m_aws_support, total_cost, args_handler.m_operating_period_in_years);
    cost_dict['summary'] = OrderedDict([
        ('compute', cost_dict['compute']['summary']['total_cost']),
        ('storage', cost_dict['storage']['summary']['total_cost']),
        ('network', cost_dict['network']['summary']['total_cost']),
        ('support', cost_dict['support']['summary']['total_cost']),
        ('total_cost', total_cost+cost_dict['support']['summary']['total_cost']),
        ]);
    if(do_print):
        print(json.dumps(cost_dict, indent=4, separators=(',', ': ')));
    return cost_dict;

def main():
    parser = argparse.ArgumentParser(description='Cost model for AWS cloud based on Amazon\'s TCO calculator');
    args_handler = AmazonArgumentsHandler(parser);
    compute_tco(args_handler, do_print=True);

if __name__ == "__main__":
    main()
