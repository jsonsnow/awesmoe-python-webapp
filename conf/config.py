#!usr/bin/python
#Filename:config.py
import config_defautl
from static.db import Dict
def merge(defaults,override):
	"""
	合拼overrid 和default 配置文档，返回字典
	"""
	r = {}
	for k,v in defaults.iteritems():
		if k in override:
			if isinstance(v,dict):
				r[k] = merge(v,override[k])
			else:
				r[k] = override[k]
		else:
			r[k] = v
	return r
def toDict(d):
	"""
	将一个字典对象转换成一个Dict对象
	"""
	D = Dict()
	for k,v in d.iteritems():
		D[k] = toDict(v) if isinstance(v,dict) else v
	return D

configs = config_default.configs
try:
	import config_override
	configs = merge(configs,configs_override.configs)
except ImportError:
	pass

configs = toDict(configs)