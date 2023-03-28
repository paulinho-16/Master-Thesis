from configparser import ConfigParser, ExtendedInterpolation

def load_config():
    config = ConfigParser(interpolation=ExtendedInterpolation())
    config.read('config.ini')
    return config

def remove_chars(string, chars):
    return string.translate({ord(i): None for i in chars})