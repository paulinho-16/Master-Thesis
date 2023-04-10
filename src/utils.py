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