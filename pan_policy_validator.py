#!/usr/bin/env python
import argparse
import configparser
import datetime
import os.path
import time

import palo_alto_firewall_analyzer.validators

from palo_alto_firewall_analyzer import pan_api
from palo_alto_firewall_analyzer.core import get_policy_validators
from palo_alto_firewall_analyzer.pan_api_helpers import load_config_package, get_and_save_API_key

DEFAULT_CONFIG_DIR = os.path.expanduser("~\\.pan_policy_analyzer\\")
DEFAULT_CONFIGFILE  = DEFAULT_CONFIG_DIR + "PAN_CONFIG.cfg"
DEFAULT_API_KEYFILE = DEFAULT_CONFIG_DIR + "API_KEY.txt"


###############################################################################
# General helper functions
###############################################################################

def create_default_config_file(config_path):
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w') as config_fh:
        analyzer_config = configparser.ConfigParser(allow_no_value=True)
        analyzer_config.add_section('analyzer')
        analyzer_config.set('analyzer', '# Mandatory: The hostname of the panorama to query')
        analyzer_config.set('analyzer', 'Panorama', 'my-panorama-hostname')
        analyzer_config.set('analyzer', '# Optional config values, used by validators')
        analyzer_config.set('analyzer', '# Mandate a specific log profile')
        analyzer_config.set('analyzer', '# Mandated Logging Profile = default')
        analyzer_config.set('analyzer', '# Ignore certain DNS prefixes in find_badhostname, as they might not always be available (e.g., DHCP)')
        analyzer_config.set('analyzer', '# Ignored DNS Prefixes = PC-,iPhone')
        analyzer_config.set('analyzer', '# Specify which Security Profile Groups are allowed and the default profile')
        analyzer_config.set('analyzer', '# Allowed Group Profiles = Security Profile Group-default,Security Profile Group-1,Security Profile Group-2')
        analyzer_config.set('analyzer', '# Default Group Profile = Security Profile Group-default')
        analyzer_config.write(config_fh)

def run_policy_validators(validators, profilepackage, output_fname):
    problems = {}
    total_problems = 0
    print("Running validators")

    for name, validator_values in validators.items():
        validator_name, validator_description, validator_function = validator_values
        validator_problems = validator_function(profilepackage)
        problems[(validator_name, validator_description)] = validator_problems
        total_problems += len(validator_problems)

    return problems, total_problems


def write_validator_output(problems, fname, format):
    supported_output_formats = ["text"]
    if format not in supported_output_formats:
        raise Exception(
            f"Unsupported output format of {format}! Output format must be one of {supported_output_formats}")

    if format == 'text':
        with open(fname, 'w') as fh:
            for validator_info, problem_entries in problems.items():
                validator_name, validator_description = validator_info

                fh.write("#" * 80 + '\n')
                fh.write(f"{validator_name}: {validator_description} ({len(problem_entries)})\n")
                fh.write("#" * 80 + '\n')
                for problem_entry in problem_entries:
                    # fh.write(f"Output for config name: {config_name} \n\n")
                    # if validator_problems:
                    fh.write(problem_entry.text + '\n')
                    # else:
                    #    fh.write('(none)\n')
                fh.write('\n')

def load_config_file(configfile, profile):
    validator_config = configparser.ConfigParser()
    # Validate config file exists
    if not os.path.isfile(configfile):
        if configfile == DEFAULT_CONFIGFILE:
            create_default_config_file(configfile)
            raise Exception(f"Config file '{configfile}' did not exist! Please edit the newly-created config and re-run.")
        else:
            raise Exception(f"Config file '{configfile}' does not exist! Exiting")

    validator_config.read(configfile)

    if profile:
        config_profile = profile
    elif len(validator_config.sections()) == 1:
        config_profile = validator_config.sections()[0]
    else:
        if len(validator_config.sections()) == 0:
            raise Exception(
                f"Unable to parse config file '{configfile}'! Specify the profile with --profile")
        else:
            raise Exception(
                f"More than one configuration profile is available in '{configfile}'! Specify the profile with --profile")
    return validator_config[config_profile]


def load_api_key(api_file):
    try:
        with open(api_file) as fh:
            api_key = fh.read().strip()
    except OSError:
        print(f"Unable to open file with API key '{api_file}'")
        api_key = get_and_save_API_key(api_file)
    return api_key


def main():
    description = f"""\
Retrieves PAN FW policy and checks it for various issues."""

    validator_descriptions = '\n'.join(f"{readable_name} - {description}" for readable_name, description, f in
                                       sorted(get_policy_validators().values()))
    epilog = f"""Here is a detailed list of the {len(get_policy_validators().keys())} supported validators:
{validator_descriptions}
"""

    parser = argparse.ArgumentParser(description=description, epilog=epilog,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", help="Run validators on all Device Groups", action='store_true')
    group.add_argument("--device-group", help="Device Group to run through validator")
    parser.add_argument("--validator", help="Only run specified validator",
                        choices=sorted(get_policy_validators().keys()), action='append')
    parser.add_argument("--quiet", help="Silence output", action='store_true')
    parser.add_argument("--config", help=f"Config file to read (default is {DEFAULT_CONFIGFILE})", default=DEFAULT_CONFIGFILE)
    parser.add_argument("--profile", help="Config profile to run through validator (defaults to first config entry)")
    parser.add_argument("--api", help=f"File with API Key (default is {DEFAULT_API_KEYFILE})", default=DEFAULT_API_KEYFILE)
    parser.add_argument("--no-api", help=f"Skip validators that require making API requests", action='store_true')
    parser.add_argument("--xml", help="Process an XML file from 'Export Panorama configuration version'. This does not use an API key and implies --no-api")
    parser.add_argument("--debug", help="Write all debug output to pan_analyzer_debug_YYMMDD_HHMMSS.log", action='store_true')
    parser.add_argument("--limit", help="Limit processing to the first N rules (useful for debugging)", type=int)
    parsed_args = parser.parse_args()

    timestamp_string = datetime.datetime.today().strftime('%Y%m%d_%H%M%S')
    if parsed_args.debug:
        pan_api.set_debug(True, f'pan_analyzer_debug_{timestamp_string}.log')

    if parsed_args.xml:
        api_key = ''
        parsed_args.no_api = True
        xml_string = "_xml"
    else:
        api_key = load_api_key(parsed_args.api)
        xml_string = ''

    validator_config = load_config_file(parsed_args.config, parsed_args.profile)

    if parsed_args.validator:
        validators = {validator: get_policy_validators()[validator] for validator in parsed_args.validator}
    else:
        validators = get_policy_validators()

    # Build the output string
    if parsed_args.device_group:
        devicegroup_string = "_" + parsed_args.device_group
    else:
        devicegroup_string = ''

    if parsed_args.validator:
        validators_string = "_" + "_".join(sorted(parsed_args.validator))
    else:
        validators_string = ''

    if parsed_args.limit:
        limit_string = "_limit" + str(parsed_args.limit)
    else:
        limit_string = ""

    if parsed_args.no_api:
        no_api_string = "_noapi"
    else:
        no_api_string = ""

    output_fname = f'pan_analyzer_output_{timestamp_string}{devicegroup_string}{xml_string}{no_api_string}{validators_string}{limit_string}.txt'

    verbose = not parsed_args.quiet
    no_api = parsed_args.no_api

    start_time = time.time()
    profilepackage = load_config_package(validator_config, api_key, parsed_args.device_group,
                                         parsed_args.limit, verbose, no_api, parsed_args.xml)
    problems, total_problems = run_policy_validators(validators, profilepackage, output_fname)
    write_validator_output(problems, output_fname, 'text')
    end_time = time.time()

    print("*" * 80)
    print(f"Full run took {end_time - start_time} seconds")
    print(f"Detected a total of {total_problems} problems")

    return


if __name__ == '__main__':
    main()
