import logging

from palo_alto_firewall_analyzer.core import BadEntry, register_policy_validator

logger = logging.getLogger(__name__)


@register_policy_validator("DisabledPolicies", "Policy objects that are disabled")
def find_disabled_policies(profilepackage):
    devicegroup_objects = profilepackage.devicegroup_objects
    pan_config = profilepackage.pan_config
    ignored_disabled_rules = set(profilepackage.settings.get('Ignored Disabled Policies', "").split(','))

    policies_to_delete = []
    for i, device_group in enumerate(devicegroup_objects):
        for policy_type in pan_config.SUPPORTED_POLICY_TYPES:
            policies = devicegroup_objects[device_group][policy_type]
            for policy_entry in policies:
                disabled = (policy_entry.find('disabled') is not None and policy_entry.find('disabled').text == 'yes')
                if disabled:
                    policy_name = policy_entry.get('name')
                    if policy_name in ignored_disabled_rules:
                        continue
                    text = f"Device Group {device_group}'s {policy_type} \"{policy_name}\" is disabled"
                    policy_to_delete = BadEntry(data=[policy_entry], text=text, device_group=device_group, entry_type=policy_type)
                    policies_to_delete.append(policy_to_delete)

    return policies_to_delete
