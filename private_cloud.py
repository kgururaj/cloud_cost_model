#!/usr/bin/env python

import sys
import json
import argparse
import math
from collections import OrderedDict
from ccc_model_common import ArgumentsHandler
from ccc_model_common import NoServerConfigurationFound
from ccc_model_common import determine_usable_storage

class PrivateCloudArgumentsHandler(ArgumentsHandler):

    m_private_cloud_hosting = 'colocation';
    m_storage_type = 'NAS';

    def add_private_cloud_optional_arguments(self, parser):
        parser.add_argument('--private_cloud_hosting', '-p', help='Type of private cloud hosting - valid options are: colocation(default), on_premise',
                default='colocation', choices=['colocation', 'on_premise']);
        parser.add_argument('--storage_type', help='Storage type - NAS(default) or SAN', default='NAS', choices=['SAN','NAS']);

    def __init__(self, argparse_obj=None, model_parameters_file=None, model_parameters_dict=None,
            num_cores=None, memory_per_core=None, storage=None, bandwidth=None, bandwidth_utilization=None,
            **kwargs):
        if(argparse_obj):
            self.add_private_cloud_optional_arguments(argparse_obj);
        ArgumentsHandler.__init__(self, argparse_obj, model_parameters_file=model_parameters_file, model_parameters_dict=model_parameters_dict,
                num_cores=num_cores, memory_per_core=memory_per_core,
                storage=storage, bandwidth=bandwidth, bandwidth_utilization=bandwidth_utilization, **kwargs);
        if(argparse_obj):
            arguments = argparse_obj.parse_args();
            self.m_private_cloud_hosting = arguments.private_cloud_hosting;
            self.m_storage_type = arguments.storage_type;

def determine_num_usable_cores_in_server_type(server_info, memory_per_core):
    max_cores_in_server = server_info['sockets']*server_info['max_cores_per_socket']
    max_usable_cores = int(float(server_info['max_memory'])/memory_per_core);
    num_usable_cores = min(max_usable_cores, max_cores_in_server);
    num_cores_per_socket = int(math.ceil(float(num_usable_cores)/server_info['sockets']));
    num_usable_cores = num_cores_per_socket*server_info['sockets'];
    return num_usable_cores;
        
def determine_server_purchase_cost(model, server_info, memory_per_core, num_usable_cores=None):
    if(not num_usable_cores):
        num_usable_cores = determine_num_usable_cores_in_server_type(server_info, memory_per_core);
    if(num_usable_cores < 1):
        raise NoServerConfigurationFound(('No valid server configuration found for specified memory per core value : %d')%(memory_per_core))
    memory_needed = num_usable_cores*memory_per_core;
    if('base_cost' in server_info and 'per_GB' in server_info and 'per_core' in server_info and 'base_memory' in server_info):
        server_cost_with_baseline_memory = server_info['per_core']*num_usable_cores + server_info['base_cost'];
        server_cost = server_info['per_GB']*memory_needed + (server_cost_with_baseline_memory - server_info['per_GB']*server_info['base_memory']);
    else:
        server_cost = server_info['cost'];
    #discount
    server_cost = (float(100-model['compute']['server_discount_percentage'])/100)*server_cost;
    return server_cost;

def determine_server_deployment_cost(model):
    return model['compute']['server_deployment_cost'];

def determine_server_maintenance_cost(model, server_purchase_cost, operating_period_in_years):
    return (float(model['compute']['server_annual_maintenance_cost_percentage'])/100)*(server_purchase_cost*operating_period_in_years);

def determine_spare_server_cost(model, server_purchase_and_maintenance_cost, operating_period):
    return (float(model['compute']['spare_server_addition_annual_percentage'])/100)*(server_purchase_and_maintenance_cost*operating_period);

def determine_num_servers(total_num_cores, num_usable_cores):
    return int(math.ceil(float(total_num_cores)/num_usable_cores));

def determine_max_num_servers_per_rack(model, server_rack_space, server_power):
    if('rack_server_capacity_limit' in model['compute']):
        rack_server_capacity_limit = model['compute']['rack_server_capacity_limit']
    else:
        rack_server_capacity_limit = model['compute']['rack_capacity'];
    by_space = int(float(rack_server_capacity_limit)/server_rack_space);
    by_power = int(float(model['compute']['rack_power_limit'])/server_power);
    return min(by_space, by_power);

def determine_num_racks(model, num_servers, num_servers_per_rack):
    return int(math.ceil(float(num_servers)/num_servers_per_rack));

def determine_rack_purchase_cost(model, num_racks):
    return model['compute']['rack_purchase_cost']*num_racks;

def determine_rack_operational_cost(model, num_racks, private_cloud_hosting, operating_period_in_years):
    op_cost_dict = model['compute']['rack_operational_cost_info'][private_cloud_hosting]
    per_rack_cost = None
    if('monthly_charge_per_rack' in op_cost_dict):
        per_rack_cost = 12*operating_period_in_years*op_cost_dict['monthly_charge_per_rack'];
    return num_racks*per_rack_cost;

def determine_pdu_cost(model, num_racks):
    return model['compute']['pdu_cost']*model['compute']['num_pdus_per_rack']*num_racks;

def determine_top_of_rack_switch_cost(model, num_racks):
    return model['compute']['top_of_rack_switch_cost']*model['compute']['num_top_of_rack_switches_per_rack']*num_racks;

def determine_total_cost_for_server(model, server_info, num_cores, memory_per_core, private_cloud_hosting, operating_period_in_years):
    num_usable_cores_per_server = determine_num_usable_cores_in_server_type(server_info, memory_per_core);
    if(num_usable_cores_per_server < 1):
        return None;
    cost_dict = OrderedDict() 
    cost_dict['num_usable_cores_per_server'] = num_usable_cores_per_server;
    cost_dict['memory_per_server'] = num_usable_cores_per_server*memory_per_core;
    cost_dict['num_sockets_per_server'] = server_info['sockets'];
    cost_dict['rack_space_per_server'] = server_info['rack_space'];
    cost_dict['num_servers'] = determine_num_servers(num_cores, num_usable_cores_per_server);
    cost_dict['server_unit_purchase_cost'] = determine_server_purchase_cost(model, server_info, memory_per_core, num_usable_cores_per_server);
    cost_dict['server_unit_power'] = server_info['power'];
    cost_dict['server_purchase_cost'] = cost_dict['num_servers']*cost_dict['server_unit_purchase_cost'];
    cost_dict['server_deployment_cost'] = cost_dict['num_servers']*determine_server_deployment_cost(model);
    cost_dict['server_maintenance_cost'] = determine_server_maintenance_cost(model, cost_dict['server_purchase_cost'], operating_period_in_years);
    cost_dict['spare_server_addition_cost'] = determine_spare_server_cost(model,
            cost_dict['server_purchase_cost']+cost_dict['server_maintenance_cost'], operating_period_in_years);
    cost_dict['max_num_servers_per_rack'] = determine_max_num_servers_per_rack(model, server_info['rack_space'], server_info['power']);
    cost_dict['num_racks'] = determine_num_racks(model, cost_dict['num_servers'], cost_dict['max_num_servers_per_rack']);
    cost_dict['rack_purchase_cost'] = determine_rack_purchase_cost(model, cost_dict['num_racks']);
    cost_dict['rack_operational_cost'] = determine_rack_operational_cost(model, cost_dict['num_racks'], private_cloud_hosting,
            operating_period_in_years);
    cost_dict['pdu_cost'] = determine_pdu_cost(model, cost_dict['num_racks']);
    cost_dict['top_of_rack_switch_cost'] = determine_top_of_rack_switch_cost(model, cost_dict['num_racks']);
    cost_dict['summary'] = OrderedDict();
    cost_dict['summary']['hardware_cost'] = cost_dict['server_purchase_cost']+cost_dict['server_deployment_cost'] \
            +cost_dict['server_maintenance_cost']+cost_dict['spare_server_addition_cost'] \
            +cost_dict['rack_purchase_cost']+cost_dict['pdu_cost']+cost_dict['top_of_rack_switch_cost'];
    cost_dict['summary']['operational_cost'] = cost_dict['rack_operational_cost'];
    cost_dict['summary']['total_cost'] = cost_dict['summary']['hardware_cost']+cost_dict['summary']['operational_cost'];
    cost_dict['summary']['total_power'] = cost_dict['server_unit_power']*cost_dict['num_servers']
    return cost_dict;

def compute_IT_cost(model, cost_dict, operating_period_in_years):
    IT_params = model['IT'];
    IT_cost_dict = OrderedDict();
    IT_cost_dict['num_compute_admins'] = int(math.ceil(float(cost_dict['compute']['num_servers'])/IT_params['num_servers_per_admin']));
    IT_cost_dict['num_storage_admins'] = int(math.ceil(float(cost_dict['storage']['raw_storage_size'])/IT_params['storage_per_admin']));
    IT_cost_dict['num_network_admins'] = float(IT_params['network_admin_percentage']*IT_cost_dict['num_compute_admins'])/100;
    IT_cost_dict['summary'] = OrderedDict();
    IT_cost_dict['summary']['total_cost'] = (IT_cost_dict['num_compute_admins']+IT_cost_dict['num_storage_admins'] \
            +IT_cost_dict['num_network_admins'])*IT_params['admin_annual_salary']*operating_period_in_years;
    return IT_cost_dict;

def select_optimal_server_configuration(model, num_cores, memory_per_core, private_cloud_hosting, operating_period_in_years, include_IT_cost):
    min_cost = 10000000000000
    min_cost_idx = -1;
    min_cost_dict = None;
    for idx in range(len(model['compute']['server_params'])):
        server_info = model['compute']['server_params'][idx];
        cost_dict = determine_total_cost_for_server(model, server_info, num_cores, memory_per_core, private_cloud_hosting, operating_period_in_years);
        if(not cost_dict):
            continue;
        IT_cost = 0;
        if(include_IT_cost):
            tmp_cost_dict = { 'compute' : { 'num_servers': cost_dict['num_servers'] }, 'storage': { 'raw_storage_size': 0 } };
            IT_cost = compute_IT_cost(model, tmp_cost_dict, operating_period_in_years)['summary']['total_cost'];
            cost_dict['IT_cost'] = IT_cost;
        if(cost_dict['summary']['total_cost']+IT_cost < min_cost):
            min_cost = cost_dict['summary']['total_cost']+IT_cost;
            min_cost_idx = idx;
            min_cost_dict = cost_dict;
    if(min_cost_idx < 0):
        raise NoServerConfigurationFound(('No valid server configuration found for specified memory per core value : %d')%(memory_per_core))
    return min_cost_dict;

def compute_storage_cost(model, raw_storage_size, private_cloud_hosting, operating_period_in_years, storage_type, backup_percentage_per_month):
    cost_dict = OrderedDict()
    cost_dict['raw_storage_size'] = raw_storage_size;
    cost_dict['usable_storage'] = determine_usable_storage(model, raw_storage_size);
    storage_params = model['storage'];
    cost_per_TB = (float(100-storage_params['discount_percentage'])/100)*storage_params['cost_per_TB'][storage_type];
    cost_dict['storage_purchase_cost'] = raw_storage_size*cost_per_TB;
    backup_data_size = (float(100+backup_percentage_per_month)/100)*raw_storage_size;
    cost_dict['backup_data_size'] = backup_data_size;
    cost_dict['num_backup_devices_needed'] = int(math.ceil(float(backup_data_size*1024*1024)/  \
            (storage_params['backup_speed_per_device_in_MBps']*storage_params['backup_time_window_in_hours']*3600)));
    cost_dict['backup_storage_cost'] = cost_dict['num_backup_devices_needed']*storage_params['backup_device_cost'];
    cost_dict['num_racks'] = determine_num_racks(model, raw_storage_size, storage_params['rack_storage_capacity']);
    cost_dict['rack_operational_cost'] = cost_dict['num_racks']*storage_params['rack_monthly_operational_cost']*12*operating_period_in_years;
    cost_dict['summary'] = OrderedDict();
    cost_dict['summary']['hardware_cost'] = cost_dict['storage_purchase_cost'];
    cost_dict['summary']['backup_cost'] = cost_dict['backup_storage_cost']; 
    cost_dict['summary']['operational_cost'] = cost_dict['rack_operational_cost'];
    cost_dict['summary']['total_cost'] = cost_dict['summary']['hardware_cost'] \
            + cost_dict['summary']['backup_cost'] + cost_dict['summary']['operational_cost'];
    return cost_dict;

def determine_bandwidth_cost(bandwidth_pricing_info, bandwidth, bandwidth_utilization, operating_period_in_years):
    if('bandwidth_cost_tiers' in bandwidth_pricing_info):
        for tier_info in bandwidth_pricing_info['bandwidth_cost_tiers']:
            if(bandwidth <= tier_info['limit']):
                return determine_bandwidth_cost(tier_info, bandwidth, bandwidth_utilization, operating_period_in_years);
    total_cost = 0;
    if('monthly_recurring_cost' in bandwidth_pricing_info):
        total_cost += operating_period_in_years*12*bandwidth_pricing_info['monthly_recurring_cost'];
    if('price_per_Mbps' in bandwidth_pricing_info):
        total_cost += operating_period_in_years*12*bandwidth_pricing_info['price_per_Mbps']*bandwidth*(float(bandwidth_utilization)/100)
    return total_cost

def compute_network_cost(model, bandwidth, bandwidth_utilization, private_cloud_hosting, operating_period_in_years, compute_hardware_cost):
    cost_dict = OrderedDict();
    network_params = model['network'];
    cost_dict['network_purchase_cost'] = (float(network_params['purchase_percentage_of_compute'])/100)*compute_hardware_cost;
    cost_dict['network_maintenance_cost'] = (float(network_params['annual_maintenance_overhead_percentage_of_purchase'])/100)* \
            cost_dict['network_purchase_cost']*operating_period_in_years;
    bandwidth_pricing_info = network_params[private_cloud_hosting]; 
    cost_dict['bandwidth_cost'] = determine_bandwidth_cost(bandwidth_pricing_info, bandwidth, bandwidth_utilization, operating_period_in_years);
    cost_dict['summary'] = OrderedDict();
    cost_dict['summary']['hardware_cost'] = cost_dict['network_purchase_cost']+cost_dict['network_maintenance_cost'];
    cost_dict['summary']['bandwidth_cost'] = cost_dict['bandwidth_cost'];
    cost_dict['summary']['total_cost'] = cost_dict['summary']['hardware_cost'] + cost_dict['summary']['bandwidth_cost'];
    return cost_dict;

def compute_tco(args_handler, do_print=False):
    model = args_handler.m_model;
    cost_dict = OrderedDict();
    cost_dict['compute'] = select_optimal_server_configuration(model, args_handler.m_num_cores, args_handler.m_memory_per_core,
            args_handler.m_private_cloud_hosting, args_handler.m_operating_period_in_years, args_handler.m_include_IT_cost);
    cost_dict['storage'] = compute_storage_cost(model, args_handler.m_storage, args_handler.m_private_cloud_hosting,
            args_handler.m_operating_period_in_years, args_handler.m_storage_type, args_handler.m_backup_percentage_per_month);
    cost_dict['network'] = compute_network_cost(model, args_handler.m_bandwidth, args_handler.m_bandwidth_utilization,
            args_handler.m_private_cloud_hosting, args_handler.m_operating_period_in_years, cost_dict['compute']['summary']['hardware_cost']);
    cost_dict['IT'] = None;
    total_cost = cost_dict['compute']['summary']['total_cost']+cost_dict['storage']['summary']['total_cost'] \
            + cost_dict['network']['summary']['total_cost'];
    if(args_handler.m_include_IT_cost):
        cost_dict['IT'] = compute_IT_cost(model, cost_dict, args_handler.m_operating_period_in_years);
        total_cost += cost_dict['IT']['summary']['total_cost'];
    cost_dict['summary'] = OrderedDict([
        ('compute', cost_dict['compute']['summary']['total_cost']),
        ('storage', cost_dict['storage']['summary']['total_cost']),
        ('network', cost_dict['network']['summary']['total_cost']),
        ('IT', cost_dict['IT']['summary']['total_cost'] if args_handler.m_include_IT_cost else None),
        ('total_cost', total_cost),
        ]);
    if(do_print):
        print(json.dumps(cost_dict, indent=4, separators=(',', ': ')));
    return cost_dict;

def main():
    parser = argparse.ArgumentParser(description='Cost model for private cloud based on Amazon\'s TCO calculator');
    args_handler = PrivateCloudArgumentsHandler(parser);
    compute_tco(args_handler, do_print=True);

if __name__ == "__main__":
    main()
