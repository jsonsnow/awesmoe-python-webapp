#encoding:utf-8
#!/usr/bin/python
#Filename:web.py

"""
这是一个简单的，轻量级的，WSGI兼容（Web Server Gaterway Interface）的web框架
WSGI概要：
	工作方式：WSGI server ----->WSGI处理函数
	作用：将HTTP原始的请求，解析，响应交给WSGI server 完成
		  让我们专心用Python编写web业务，就是是WSGI处理函数
		  所有WSGI是HTTP的一种高级封装
	例子：
		WSGI 处理函数
			def application(environ,start_response):
				method = environ['REQUEST_METHOD']
				path = environ['PATH_INFO']
				if method =='GET' and path == '/':
					return handle_home(environ,start_response)
					pass
				if method == 'POST' and path == '/signin:
					return handle_signin(environ,start_response)
					pass

			wsgi server
				def run(self,port = 9000,host = '127.0,.0.1'):
					from swgiref.simpler_server import make_server
					from xxxx import application
					server = make_server(host,port,application)
					server.serve_forever()
					pass

设计web框架的原因：
	1.wsgi提供的接口虽然比http接口高级不少，但和web App的处理逻辑比，还是比较低级
	我们需要在WSGI接口上进一步抽象，让我们专注于用一个函数处理一个url
	至于url到函数的映射，就交给web框架来做

设计web框架的接口：
	1.URL路由：用于URL到处理函数的映射
	2.URL拦截：用于根据URL做权限检测
	3.视图：用于HTML页面生成
	4.数据模型：用于抽取数据
	5.事务数据：request数据和response数据的封装(thread local)
"""
import types,os,re,cgi,sys,time,datetime,functools,mimetypes,threading,logging,traceback,urllib
from db import Dict
import utils

try:
	from cStringIO import StringIO
except ImportError:
	from StringIO import StringIO

ctx = threading.local()
_RE_RESPONSE_STATUS = re.compile(r'^\d\d\d(\ [\w\ ]+)$')
_HEAD_X_POWERED_BY = ('X-Powered-By','transwarp/1.0')

#用于时区转换
_TIMEDELTA_ZERO = datetime.timedelta(0)
_RE_TZ = re.compile('^([\+\-])([0-9]{1,2})\:([0-9]{1,2})$')

#response_status
_RESPONSE_STATUSES = {
	# Informational
	100:'Continue',
	101:'Swithing Protocols',
	102:'Processing',

	#Successful
	200:'OK',
	201:'Created',
	202:'Accepted',
	203:'Non-Authoritative Informationa',
	204:'No Content',
	205:'Reset Content',
	206:'Partial Content',
	207:'Multi Status',
	226:'IM Used',

	#Redirection
	300:'Multiple Choices',
	301:'Moved Permanently',
	302:'Found',
	303:'See Other',
	304:'Not Modified',
	305:'Use Proxy',
	307:'Temporary Redirect',

	#Client Error
	400:'Bab Request',
	401:'Unauthorized',
	402:'Payment Required',
	403:'Forbidden',
	404:'Not Found',
	405:'Method Not Allowed',
	406:'Not Acceptable',
	407:'Proxy Authoritatication Required',
	408:'Request Timeout',
	409:'Conflict',
	410:'Gone',
	411:'Lenth Required',
	412:'Precondition Failed',
	413:'Request Entity Too Large',
	414:'Request URI Too Long',
	415:'Unsupported Media Type',
    416: 'Requested Range Not Satisfiable',
    417: 'Expectation Failed',
    418: "I'm a teapot",
    422: 'Unprocessable Entity',
    423: 'Locked',
    424: 'Failed Dependency',
    426: 'Upgrade Required',

    # Server Error
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
    505: 'HTTP Version Not Supported',
    507: 'Insufficient Storage',
    510: 'Not Extended',
}

_RESPONSE_HEADERS = (
    'Accept-Ranges',
    'Age',
    'Allow',
    'Cache-Control',
    'Connection',
    'Content-Encoding',
    'Content-Language',
    'Content-Length',
    'Content-Location',
    'Content-MD5',
    'Content-Disposition',
    'Content-Range',
    'Content-Type',
    'Date',
    'ETag',
    'Expires',
    'Last-Modified',
    'Link',
    'Location',
    'P3P',
    'Pragma',
    'Proxy-Authenticate',
    'Refresh',
    'Retry-After',
    'Server',
    'Set-Cookie',
    'Strict-Transport-Security',
    'Trailer',
    'Transfer-Encoding',
    'Vary',
    'Via',
    'Warning',
    'WWW-Authenticate',
    'X-Frame-Options',
    'X-XSS-Protection',
    'X-Content-Type-Options',
    'X-Forwarded-Proto',
    'X-Powered-By',
    'X-UA-Compatible',
)
class UTC(datetime.tzinfo):
	"""
	tzinfo 是一个基类，用于给datetime对象分配一个时区
	使用方式是 把这个子类对象传递给datetime.tzinfo属性

	"""

	def __init__(self,utc):
		utc = str(utc.strip().upper())
		mt = _RE_TZ.match(utc)
		if mt:
			minus = mt.group(1) =='_'
			h = int(mt,group(2))
			m = int(mt.group(3))
			if minus:
				h,m = (-h),(-m)
			self._utcoffset = datetime.timedelta(hours = h,minutes =m)
			self._tzname = 'UTC%s' % utc
		else:
			raise ValueError('bad utc time zone')

	def utcoffset(self,dt):
		"""
		表示与标准时区的偏移量
		"""
		return self._utcoffset
	def dst(self,dt):
		"""
		Daylight Saving Time 夏令时
		"""
		return _TIMEDELTA_ZERO

	def tzname(self,dt):
		"""
		所在时区名字
		"""
		return self._tzname

	def __str__(self):
		return 'UTC timezone info object(%s)' % self._tzname

	__repr__ = __str__

#用于异常处理
class _HttpError(Exception):
	"""
	HttpError that defines http error code.
	"""

	def __init__(self,code):
		"""
		Init an HttpError with response code
		"""
		super(_HttpError,self).__init__()
		self.status = '%d %s' % (code,_RESPONSE_STATUSES[code])
		self._headers = None

	def header(self,name,value):
		"""
		添加header,如果header为空则添加powered by header
		"""
		if not self._headers:
			self._headers = [_HEAD_X_POWERED_BY]
		self._headers.append((name,value))

	@property
	def header(self):
		"""
		使用setter方法实现header属性
		"""
		if hasattr(self,'_headers'):
			return self._headers
		return []

	def __str__(self):
		return self.status

	__repr__ = __str__

class _RedirectError(_HttpError):
	"""
	RedirectError that defines http redirect code
	"""
	def __init__(self,code,location):
		"""
		Init an HttpError with response code
		"""
		super(_RedirectError,self).__init__(code)
		self.location = location

	def __str__(self):
		return '%s,%s' % (self.status,self.location)
	__repr__  = __str__

class HttpError(object):
	"""
	HTTP ExceptionS
	"""
	@staticmethod
	def badrequest():
		"""

		"""
		return _HttpError(400)

	@staticmethod
	def unauthorized():
		return _HttpError(401)

	@staticmethod
	def forbidden():
		"""
		"""
		return _HttpError(403)

	@staticmethod
	def notfound():
		"""
		"""
		return _HttpError(404)

	@staticmethod
	def conflict():
		"""
		"""
		return _HttpError(409)

	@staticmethod
	def internalerror():
		"""
		"""
		return _HttpError(500)

	@staticmethod
	def redirect(location):
		"""
		"""
		return _RedirectError(301,location)

	@staticmethod
	def found(location):
		"""
		"""
		return _RedirectError(302,location)

	@staticmethod
	def seeother(location):
		"""
		"""
		return _RedirectError(303,location)

_RESPONSE_HEADER_DICT = dict(zip(map(lambda x:x.upper(),_RESPONSE_HEADERS),_RESPONSE_HEADERS))

class Request(object):
	"""
	请求对象，用于获取所有http请求信息
	"""
	def __init__(self,environ):
		"""
		environ wsgis 处理函数里面的那个enverion
		wsgi server 调用处理函数时候传入的
		包含了用户请求的所有数据
		"""
		self._environ = environ

	def _pares_input(self):
		"""
		将通过wsgi传入过来的参数，解析成一个字典对象返回
		比如；request({'REQUEST_METHOD':'POST','wsgi.input':StringIO('a = 1&b=m.....')})
			这里解析的就是wsgi.input 对象里面的字节流
		"""

		def _convert(item):
			if isinstance(item,list):
				return [utils.to_unicode(i.value) for i in item]
			if item.filename:
				return MultipartFile(item)
			return utils.to_unicode(item.value)
		fs = cgi.FieldStorage(fp = self._environ['wsgi.input'],environ = self._environ,keep_blank_values =True)
		inputs = dict()
		for key in fs:
			inputs[key] = _convert(fs[key])
		return inputs

	def _get_raw_input(self):
		"""
		将从swgi解析出来的数据字典，添加为Request对象的属性
		然后，返回该字典
		"""
		if not hasattr(self,'_raw_input'):
			self._raw_input = self._pares_input()
		return self._raw_input

	def __getitem__(self,key):
		"""
		实现通过键值访问Request对象里面的数据，如果该键有多个值，则返回第一个值
		如果键不存在，则会raise keyError
		"""
		r = self._get_raw_input()[key]
		if isinstance(r,list):
			return r[0]
		return r

	def get(self,key,default = None):
		"""

		"""
		r = self._get_raw_input().get(key, default)
		if isinstance(r,list):
			return r[0]
		return r

	def gets(self,key):
		"""
		Get multiple value for specified key
		"""
		r = self._get_raw_input()[key]
		if isinstance(r,list):
			return r[:]
		return r

	def input(self,**kw):
		"""

		"""
		copy = Dict(**kw)
		raw = self._get_raw_input()
		for k,v in raw.iteritems():
			copy[k] = v[0] if isinstance(v,list) else v
		return copy

	def get_body(self):
		"""
		"""
		fp = self._environ['wsgi.input']
		return fp.read()

	@property
	def remote_addr(self):
		"""
		"""
		return self._environ.get('REMOTE_ADDR','0.0.0.0')
	@property
	def document_root(self):
		"""
		"""
		return self._environ.get('DOCUMENT_ROOT','')
	@property
	def query_string(self):
		"""
		"""
		return self._environ.get('QUERY_STRING','')
	@property
	def environ(self):
		"""
		"""
	@property
	def request_method(self):
		"""
		"""
		return self._environ('REQUEST_METHOD')
	@property
	def path_info(self):
		"""
		"""
		return urllib.unquote(self._environ.get('PATH_INTO',''))
	@property
	def host(self):
		"""
		"""
		return self._environ.get('HTTP_HOST','')
	def _get_headers(self):
		"""
		从environ里获取HTTP开通的header
		"""
		if not hasattr(self,'_headers'):
			hdrs = {}
			for k,v in self._environ.iteritems():
				if k.startwith('HTTP_'):		
					hdrs[k[5:].replace('_','-').upper()] = v.decode('utf-8')
			self._headers = hdrs
		return self._headers
	@property
	def headers(self):
		"""
		"""
		return dict(**self._get_headers())

	def  header(self,header,default = None):
		"""
		获取指定的header
		"""
		return self._get_headers().get(header.upper(),default)

	def _get_cookies(self):
		"""
		"""
		if not hasattr(self,'_cookies'):
			cookies = {}
			cookie_str = self._environ.get('HTTP_COOKIE')
			if cookie_str:
				for c in cookie_str.split(';'):
					pos = c.find('=')
					if pos > 0:
						cookies[c[:pos].strip()] = utils.upquote(c[pos+1:])
			self._cookies = cookies
		return self._cookies

	@property
	def cookies(self):
		"""
		"""
		return Dict(**self._get_cookies())
	def cookie(self,name,default = None):
		"""
		"""
		return self._get_cookies().get(name,default)

class Response(object):
	def __init__(self):
		self._status = '200 OK'
		self._headers = {'CONTENT-TYPE':'text/html;charset = utf-8'}

	def unsert_header(self,name):
		"""
		删除指定的header
		"""
		key = name.upper()
		if key not in _RESPONSE_HEADER_DICT:
			key = name
		if key in self._headers:
			del self._headers[key]
	def set_header(self,name,value):
		"""
		"""
		key = name.upper()
		if key not in _RESPONSE_HEADER_DICT:
			key = name
		self._headers[key] = utils.to_str(value)

	def header(self,name):
		"""
		获取Response Header里单个Header的值，非大小敏感
		"""
		key = name.upper()
		if key not in _RESPONSE_HEADER_DICT:
			key = name
		return self._headers.get(key)

	@property
	def headers(self):
		"""
		setter 构造的属性，以[(key1,value1),(key2,value2)....]形式存储，所有header值
		包括cookies的值
		"""
		L = [(_RESPONSE_HEADER_DICT.get(k,k),v) for k,v in self._headers.iteritems()]
		if hasattr(self,'_cookies'):
			for v in self._cookies.iteritems():
				L.append(('Set-Cookie',v))
		L.append(_HEAD_X_POWERED_BY)
		return L

	@property
	def content_type(self):
		"""
		setter 方法实现的属性，用户保持header:Content-type的值
		"""
		return self.header('CONTENT-TYPE')
	@content_type.setter
	def content_type(self,value):
		"""
		让content-type属性可写，及设置Content-Type Header
		"""
		if value:
			self.set_header('CONTENT-TYPE',value)
		else:
			self.unsert_header('CONTENT-TYPE')

	@property
	def content_length(self):
		"""
		获取Content-Length Header 的值
		"""
		return self.header('CONTENT-LENGTH')
	@content_length.setter
	def content_length(self,value):
		"""
		设置Content-Length Header的值
		"""
		self.set_header('CONTENT-LENGTH',str(value))

	def delete_cookie(self,name):
		"""
		delete a cookie immediately
		Args:
			name:the cookie name
		"""
		self.set_cookie(name,'__deleted__',expires=0)
	def set_cookie(self,name,value,max_age = None,expires =None,path='/',domain = None,secure = False,http_only = True):	
		"""
		Set a cookie
		Args:
		 	name:the cookie name
		 	value:the cookie value
		 	max_age:optional,seconds of cookie`s max age
		 	expires:optional,unix timestamp,datetime or date object that indicate an absulute time of
		 	the expires time of cookie.Note that if specified,the max_age will be ignored.
		 	path: the cookie path 
		 	domain:the cookie domain,default to None
		 	secure:if the cookie secure,default to False
		 	http_only:if the cookie is for http only,default to true for better safty
		 				(client-side script cannot access cookies with HttpOnlu flag)

		"""
		if not hasattr(self,'_cookies'):
			self._cookies = {}
		L = ['%s=%s' % (utils.quote(name),utils.quote(value))]
		if expires is not None:
			if isinstance(expires,(float,int,long)):
				L.append('Expires=%s' % datetime.datetime.fromtimestamp(expires,UTC_0).strftime('%a,%d-%b-%Y %H:%M:%S GMT'))
			if isinstance(expires,(datetime.date,datetime.datetime)):
				L.append('Expires=%s'%expires.astimezone(UTC_0).strftime('%a,%d-%b-%Y %H:%M:%S GMT'))
		elif isinstance(max_age,(int,long)):
			L.append('Max-Age=%d'%max_age)
		L.append('Path = %s'%path)
		if domain:
			L.append('Domain = %s'%domain)
		if secure:
			L.append('Secure')
		if http_only:
			L.append('HttpOnly')
		self._cookies[name] = ';'.join(L)

	def unset_cookie(self,name):
		"""
		Unsert a cookie
		"""
		if hasattr(self,'_cookies'):
			if name in self._cookies:
				del self._cookies[name]

	@property
	def status_code(self):
		"""
		Get response status code as int
		"""
		return int(self,_status[:3])

	@property
	def status(self):
		"""
		Get response status.Default to '200 OK'
		"""
		return self._status
	@status.setter
	def status(self,value):
		"""
		Set response status as int or str
		"""
		if isinstance(value,(int,long)):
			if 100 <= value <= 999:
				st = _RESPONSE_STATUSES.get(value,'')
				if st:
					self._status = '%d %s'%(value,st)
				else:
					self._status = str(value)
			else:
				raise ValueError('Bad response code :%d' % value)
		elif isinstance(value,basestring):
			if isinstance(value,unicode):
				value = value.encode('utf-8')
			if _RE_RESPONSE_STATUS.match(value):
				self._status = value
			else:
				raise ValueError('Bad response code:%s' % value)
		else:
			raise TypeError('Bad type of response code')

_re_route = re.compile(r'(:[a-zA-Z_]\w)')
def get(path):
	"""

	"""
	def _decorator(func):
		func.__web_route__ = path
		func.__web_method__ = 'GET'
		return func
	return _decorator

def post(path):
	"""
	"""
	def _decorator(func): 
		func.__web_route__ = 'path'
		func.__web_method__ = 'POST'

def _build_regex(path):
	"""
	用于将路径转换成正则表达式，并捕获其中的参数
	"""
	re_list = ['^']
	var_list = []
	is_var = False
	for v in _re_route.split(path):
		if is_var:
			var_name = v[1:]
			var_list.append(var_name)
			re_list.append(r'(?p<%s>[^\/]+)'%var_name)
		else:
			s = ''
			for ch in v:	
				if '0' <= ch <= '9':
					s+=ch
				elif 'A' <=ch<='Z':
					s+=ch
				elif 'a'<= ch <= 'z':
					s += ch
				else:
					s = s + '\\' + ch
			re_list.append(s)
		is_var = not is_var
	re_list.append('$')
	return ''.join(re_list)
def _static_file_generator(fpath,block_size = 8192):
	"""
	读取静态文件的一个生产器
	"""
	with open(fpath,'rb') as f:
		block = f.read(block_size)
		while block:
			yield block 
			block = f.read(block_size)

class Route(object):
	"""
	动态路由对象，处理 装饰器捕获的url和函数
	"""
	def __init__(self,func):
		"""
		path:通过method的装饰器捕获的path
		method:通过method的装饰器捕获的method
		is_static:路径是否含变量，含变量为true
		func:方法装饰器里定义的函数
		"""
		self.path = func.__web_route__
		self.method = func.__web_method__
		self.is_static = _re_route.search(self.path) is None
		if not self.is_static:
			self.route = re.compile(_build_regex(self.path))
		self.func = func

	def match(self,url):
		"""
		传入url，返回捕获的变量
		"""
		m = self.route.match(url)

	def __call__(self,*arg):
		"""
		实例对象直接调用时，执行传入的函数对象
		"""
		return self.func(*args)
	def __str__(self,*args):
		if self.is_static:
			return 'Route(static,%s,path=%s)'%(self.method,self.path)
		return 'Route(dynamic,%s,path=%s)'%(self.method,self.path)
	__repr__ = __str__

class StaticFileRoute(object):
	"""
	静态路由对象和Route相对应
	"""
	def __init__(self):
		self.method = 'GET'
		self.is_static = False
		self.route = re.compile('^/static/(.+)&')

	def match(self,url):
		if url.startwith('/static/'):
			return (url[1:],)
		return None

	def __call__(self,*args):
		fpath = os.path.join(ctx.application.document_root,args[0])
		if not os.path.isfile(fpath):
			raise HttpError.notfound()
		ftext = os.path.splitext(fpath)[1]
		ctx.response.content_type = mimetypes.types_map.get(fext.lower(),'application/octet-stream')
		return _static_file_generator(fpath)

class MultipartFile(object):
	"""
	Multipart file storage get from request input
	"""
	def __init__(self,storage):
		self.filaname = utils.to_unicode(storage.filaname)
		self.file = storage.file


class Template(object):
	def __init__(self,template_name,**kw):
		"""
		Init a template object with template name ,model as dict,and additional kw will 
		append to model
		"""
		self.template_name = template_name
		self.model = dict(**kw)

class TemplateEngine(object):
	"""
	Base template engine
	"""
	def __call__(self,path,model):
		return '<!--override this method to render template-->'

class Jinja2TemplateEngine(TemplateEngine):
	"""
	Render using jinja2 template engine

	"""

def _debug():
	"""
	return	
	"""
	pass

def _default_error_handler(e,start_response,is_debug):
	"""
	用于处理异常，主要是相应一个异常页面
	"""

	if isinstance(e,HttpError):
		logging.info('HttpError:%s'%e.status)
		headers = e.headers[:]
		headers.append(('Content-Type','text/html'))
		start_response(e.status,headers)
		return ('<html><body><h1>%s</h1></body></html>' % e.status)
	logging.exception('Exception')
	start_response('500 internal Server Erro',[('Content-Type','text/html'),_HEAD_X_POWERED_BY])
	if is_debug:
		return _debug()
	return ('<html><body><h1>500 Internal Server Erro</h1><h3>%s</h3></body></html>'%str(e))

def view(path):
	"""
	被装饰的函数，需要返回一个字典对象，用于渲染
	装饰器通过Template类将path和dict 关联在一个Template对象上
	"""
	def _decorator(func):
		@functools.wraps(func)
		def _wrapper(*args,**kw):
			r = func(*args,**kw)
			if isinstance(r,dict):
				logging.info('return Template')
				return Template(path,**r)
			raise ValueError('Expect return a dict when using@view()decorator')
		return _wrapper
	return _decorator

###################################
# 实现URL拦截器
# 主要interceptor的实现
###################################
_RE_INTERCEPTOR_STARTS_WITH = re.compile(r'^([^\*\?]+)\*?$')
_RE_INTERCEPTOR_ENDS_WITH = re.compile(r'^\*([^\*\?]+)$')

def _build_pattern_fn(pattern):
	"""
	传入需要匹配的字符串：url
	返回一个函数，该函数接收一个字符串参数，检测该字符串是否符合parttern
	"""
	m = _RE_INTERCEPTOR_STARTS_WITH.match(pattern)
	if m:
		return lambda p:p.startswith(m.group(1))
	m = _RE_INTERCEPTOR_ENDS_WITH.match(pattern)
	if m:
		return lambda p:p.endswith(m.group(1))
	raise ValueError('Invaild pattern definition in tnterceptor.')

def interceptor(pattern='/'):
	"""
	"""
	def _decorator(func):
		func._interceptor__ = _build_pattern_fn(pattern)
		return func
	return _decorator

def _build_inerceptor(func,next):
	"""
	拦截器接受一个next函数，这样一个拦截器就可以决定调用next()继续处理请求还是直接返回
	"""
	def _wrapper():
		if func.__interceptor_(ctx.request.path_info):
			return func(next)
		else:
			return next()
	return _wrapper


def _build_interceptor_chain(last_fn,*interceptor):
	"""
	Build interceptor chain
	"""
	L = list(interceptors)
	L.reverse()
	fn = last_fn
	for f in L:
		fn = _build_pattern_fn(f,fn)
	return fn

def _load_module(model_name):
	"""
	Load module from name as str
	"""
	last_dot = model_name.rfind('.')
	if last_dot == (-1):
		return __import__(model_name,globals(),locals())
	from_module = module_name[:last_dot]
	import_module = module_name[last_dot+1]
	m = __import__(from_module,globals(),locals(),[import_module])
	return getattr(m,import_module)

############################################
#全局WSGIApplication的类，实现WSGI接口
#WSGIApplication封装了wsgi Serve(run方法) 和wsgi处理函数（wsgi静态方法）
#上面的所有的功能都是对wsgi处理函数的装饰
###########################################

class WSGIApplication(object):

	def __init__(self,document_root=None,**kw):
		"""
		Init a WSGIApplication
		Args:
			document_root:document root path
		"""
		self._running = False
		self._document_root = document_root

		self._interceptors = []
		self._template_engin = None

		self._get_static = {}
		self._post_static = {}

		self._get_dynamic = []
		self._post_dynamic = []

	def _check_not_running(self):
		"""
		检测app对象，是否运行
		"""
		if self._running:
			raise RuntimeError('Cannot modify WSGIApplication when running')

	@property 
	def template_engin(self,engine):
		"""
		设置app使用模板
		"""
		self._check_not_running()
		self._template_engine = engine

	def add_module(self,mod):
		self._check_not_running()
		m = mod if type(mod) == types.ModuleType else _load_module(mod)
		logging.info('Add module :%s'% m.__name__)
		for name in dir(m):
			fn = getattr(m,name)
			if callable(fn) and hasattr(fn,'__web_route__') and hasattr(fn,'__web_method__'):
				return self.add_url(fn)

	def add_url(self,func):
		"""
		添加url,主要是添加路由
		"""
		self._check_not_running()
		route = Route(func)
		if route.is_static:
			if route.method == 'GET':
				self._get_static[route.path] = route
			if route.method == 'POST':
				self._post_static[route.path] = route
		else:
			if route.method == 'GET':
				self._get_dynamic.append(route)
			if route.method == 'POST':
				self._post_dynamic.append(route)
		logging.info('Add route:%s' % str(route))

	def add_interceptor(self,func):
		"""
		添加拦截器
		"""
		self._check_not_running()
		self._interceptors.append(func)
		logging.info('Add interceptor:%s' % str(func))

	def run(self,port =9000,host='127.0.0.1'):
		"""
		启动python自带的wsgi server
		"""
		from wsgiref.simple_server import make_server
		logging.info('application (%s) will start at %s:%s...' % self._document_root,host,port)
		server = make_server(host,port,self.get_wsgi_application(debug=True))
		server.serve_forever()

	def get_wsgi_application(self,debug=False):
		self._check_not_running()
		if debug:
			self._get_dynamic.append(StaticFileRoute())
		self._running = True
		_application = Dict(ducument_root= self._document_root)

		def fn_route():
			request_method = ctx.request.request_method
			path_info = ctx.request.path_info
			if request_method == 'GET':
				fn = self._get_static.get(path_info,None)
				if fn:
					return fn()
				for fn in self._get_dynamic:
					args = fn.match(path_info)
					if args:
						return fn(*args)
				raise HttpError.notfound()
			if request_method == 'POST':
				fn = self.post_static.get(path_info,None)
				if fn:
					return fn()
				for fn in self.get_dynamic:
					args = fn.match(path_info)
					if args:
						return fn(*args)
				raise HttpError.notfound()
			raise badrequest()
		fn_exec = _build_interceptor_chain()







