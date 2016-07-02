#!usr/bin/python
#-*- coding:utf-8 -*-
"""
实现以json数据格式进行交换的restful api
设计原因：
	由于api就是把web app的功能全部封装，所以，通过api操作数据。
	可以极大的把前端和后端的代码隔离，使得后端代码易于测试
	前端代码编写更简单
实现方式：
	一个api也是一个Url的处理函数，我们希望能够直接通过一个@api来
	把函数变成json格式的rest api,因此我们需要实现一个装饰器，
	由该装饰器将函数返回的数据处理成json格式
"""
import json
import logging
import functools

from static.web import ctx

def dumps(obj):
	"""
	serialize obj to a json formatted str
	序列化对象
	"""
	return json.dumps(obj)

class APIError(StandardError):
	"""
	the base APIError which contains error
	存储所有API异常对象的数据
	"""
	def __init__(self,error,data='',message=''):
		super(APIError,self).__init__(message)
		self.error = error
		self.data = data
		self.message = message

class APIValueError(APIError):
	"""
	Indicate the input value has error or invalid,
	the data specifies the error field of input form.
	输入不合法异常对象
	"""
	def __init__(self,field,message=''):
		super(APIValueError,self).__init__('value:invalid',field,message)

class APIResourceNotFoundError(APIError):
	"""
	输入不合法，异常对象
	"""
	def __init__(self,field,message=''):
		super(APIResourceNotFoundError,self).__init__('value:notfound',field,message)

class APIPermissionError(APIError):
	"""
	权限异常对象
	"""
	def __init__(self,message=''):
		super(APIPermissionError,self).__init__('permission:forbidden','permission',message)

def api(func):
	"""
	a decorator that makes a function to json api,makes the return value to json
	将函数返回结果转换成json的准时器
	@api需要对Error进行处理，我们定义一个APIError,
	这种Error是指API调用时发生了逻辑错误（比如用户不存在
	其他的Error视为Bug,返回的错误代码为internalerro
	"""
	@functools.wraps(func)
	def _wrapper(*args,**kw):
		try:
			r = dumps(func(*args,**kw))
		except APIError,e:
			r = json.dumps(dict(error=e.error,data=e.data,message=e.message))
		except Exception,e
			logging.exception(e)
			r = json.dumps(dict(error='internalerror',data=e.__class__.__name__,message=e.message))
		ctx.response.content_type = 'appliaction/json'
		return r
	return _wrapper

if __name__ == '__main__':
	import doctest
	doctest.testmod()
