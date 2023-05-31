import re
import xml.etree.cElementTree as ET
from configparser import ConfigParser, ExtendedInterpolation

def load_config():
    config = ConfigParser(interpolation=ExtendedInterpolation())
    config.read('config.ini')
    return config

def remove_chars(string, chars):
    return string.translate({ord(i): None for i in chars})

def write_xml(body, file):
    ET.indent(body, space='\t')
    tree = ET.ElementTree(body)
    tree.write(file, encoding='UTF-8', xml_declaration=True)

def get_sensors_coverage(coverage_file):
        sensors_coverage = {} # sensor : [edges]
        with open(coverage_file, 'r') as f:
            lines = f.readlines()

            for line in lines:
                if line.startswith('###'):
                    sensor = line.split('sensor')[-1].strip()[:-1]
                    sensors_coverage[sensor] = []
                elif line != '\n':
                    sensors_coverage[sensor].append(line.strip())

        return sensors_coverage

def get_free_variables(free_variables_file):
    free_variables = {}
    pattern = r"### (.*?): \[(.*?)\]"
    with open(free_variables_file, 'r') as f:
        content = f.read()

        matches = re.findall(pattern, content)
        for match in matches:
            node = match[0].split('of ')[-1]
            vars = [var.strip("'") for var in match[1].split(', ')]
            free_variables[node] = vars

    return free_variables