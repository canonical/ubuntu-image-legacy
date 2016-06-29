"""Partition roles."""


from enum import Enum
from ubuntu_image.helpers import as_size


class ESP:
    def __init__(self, yaml):
        self.yaml = yaml
        # Dig out some useful information.
        partition = yaml['partitions'][0]
        self.size = as_size(partition['size'])
        self.files = [
            (section['source'], section['dest'])
            for section in partition['files']
            ]


class Roles(Enum):
    esp = ESP


def get_role(yaml):
    partitions = yaml['partitions']
    assert len(partitions) == 1, partitions
    role = partitions[0]['role']
    return Roles[role.lower()].value(yaml)
