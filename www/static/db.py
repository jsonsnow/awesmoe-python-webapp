#db.py
#encoding:utf-8
import time
import uuid
import functools
import threading
import logging
import mysql.connector

engine = None

def next_id(t = None):
	'''生成一个唯一 id 由当前时间+随机数拼接得到'''
	if t is None:
		t = time.time()
	return '%015d%s000' % (int(t*1000),uuid.uuid4().hex)

def _profiling(start,sql=''):
	'''用于解析sql的执行时间'''
	t = time.time() - start
	if t > 0.1:
		logging.warning('[PROFILING] [DB]%s:%s'%(t.sql))
	else:
		logging.info('[PROFILING] [DB] %s:%s') % (t,sql)
def create_engine(user,password,database,host = '127.0.0.1',port = 3306,**kw):
	"""
	db模型的核心函数，用于连接数据库，生成全局对象engine
	engine对象持有数据库连接
	"""

	global engine
	if engine is not None:
		raise DBError('Engine is already initialized')
	params = dict(user = user,password = password,database = database,host = host,port = port)
	defaults = dict(use_unicode = True,charset = 'utf8',collation = 'utf8_general_ci',autocommit =False)
	for k,v in defaults.iteritems():
		params[k] = kw.pop(k,v)
	params.update(kw)
	params['buffered'] =True
	engine = _Engine(lambda:mysql.connector.connect(**params))
	# test connection
	logging.info('Init mysql engine <%s> ok'%hex(id(engine)))

def connection():
	'''
	db模型的核心函数，用于获取一个数据库连接
	通过_ConnectionCtx对_db_ctx封装，使得惰性连接可以自动获取和释放
	也就是可以with语法来处理数据库连接
	'''
	return _ConnectionCtx()

def with_connection(func):
	'''
	设计一个装饰器 替换with语法，让代码更优雅
	比如：
		@with_connection
		def foo(*args,**kw):
			f1()
			f2()
			f3()
	'''
	@functools.wraps(func)
	def _wrapper(*args,**kw):
		with _ConnectionCtx():
			return func(*args,**kw)
	return _wrapper

def transaction():
	"""
	db模型的核心函数，用于实现事务功能
	支持事务：
		with db.transaction():
			db.select('...')
			db.update('...')
	支持事务且套：
		with db.transaction():
			transaction1
			transaction2
			transaction3
			....
	"""
	return _TranscationCtx()

def with_transaction(func):
	"""
	设计一个装饰器 替换with语法，让代码更优雅
	比如：
		@with_transaction
		def do_in_transaction():
			
	"""
	@functools.wraps(func)
	def _wrapper(*args,**kw):
		start = time.time()
		while _TranscationCtx():
			func(*args,**kw)
		_profiling(start)
	return _wrapper
		
@with_connection
def _select(sql,first,*args):
	"""
	执行SQL,返回一个结果，或多个结果组成的列表
	"""
	global _db_ctx
	cursor = None
	sql = sql.replace('?','%s')
	logging.info('SQL:%s,ARGS:%s' % (sql,args))
	try:
		cursor = _db_ctx.connection.cursor()
		cursor.execute(sql,args)
		if cursor.description:
			names = [x[0] for x in cursor.description]
		if first:
			values = cursor.fetchone()
			if not values:
				return None
			return Dict(names,values)
		return [Dict(names,x) for x in cursor.fetchall()]
	finally:
		if cursor:
			cursor.close()

def select_one(sql,*args):
	return _select(sql,True,*args)

def select_init(sql,*args):
	d = _select(sql,True,*args)
	if len(d) != 1:
		raise MultiColumsError('Expect only one column.')
	return d.values()[0]

def select(sql,*args):
	""

	""
	return _select(sql,False,*args)

@with_connection
def _update(sql,*args):
	"""
	执行update语句，返回update的行数
	"""
	global _db_ctx
	cursor = None
	sql = sql.replace('?','%s')
	logging.info('SQL:%s ARGS:%s'%(sql,args))
	try:
		cursor = _db_ctx.connection.cursor()
		cursor.execute(sql,args)
		r = cursor.rowcount
		if _db_ctx.transactions == 0:
			# no transaction enviroment
			logging.info('auto commit')
			_db_ctx.connection.commit()
		return r
	finally:
		if cursor:
			cursor.close()

def update(sql,*args):
	"""
	执行update语句，返回update的行数
	"""
	return _update(sql,*args)

def insert(table,**kw):
	"""
	执行insert语句
	"""
	cols,args = zip(*kw.iteritems())
	sql = 'insert into `%s` (%s) values (%s)' % (table, ','.join(['`%s`' % col for col in cols]), ','.join(['?' for i in range(len(cols))]))
	return _update(sql, *args)


class Dict(dict):
	"""
	字典对象
	实现一个简单的可以通过属性访问的字典，比如x.key= value
	"""
	def __init__(self,name=(),values=(),**kw):
		super(Dict,self).__init__(**kw)
		for k,v in zip(name,values):
			self[k] = v
	def __getattr__():
		try:
			return self[key]
		except KeyError:
			raise AttributeError(r" 'Dict object has no attribue %s‘" % key)
	def __setattr__(self,key,value):
		self[key] = value

class _Engine(object):
	def __init__(self,connect):
		self._connect = connect
	def connect(self):
		return self._connect()

class _LasyConnection(object):
	"""
	惰性连接对象
	仅当需要cursor对象时，才连接数据库，获取连接
	"""
	def __init__(self):
		self.connection = None
	def cursor(self):
		if self.connection is None:
			_connection = engine.connect()
			logging.info('[CONNECTION] [OPEN] connection <%s>...'%hex(id(_connection)))
			self.connection = _connection
		return self.connection.cursor()
	def commit(self):
		self.connection.commit()

	def rollback(self):
		self.connection.rollback()
	def cleanup(self):
		if self.connection:
			_connection = self.connection
			self.connection = None
			logging.info('[CONNECTION] [CLOSE] connection <%s>...'%hex(id(_connection)))
			_connection.close()


class _DbCtx(threading.local):
	def __init__(self):
		self.connection = None
		self.transactions = 0
	def is_init(self):
		return not self.connection is None
	def init(self):
		self.connection = _LasyConnection()
		self.transactions = 0
	def cleanup(self):
		self.connection.cleanup()
		self.connection = None
	def cursor(self):
		return self.connection.cursor()
_db_ctx = _DbCtx()

class _ConnectionCtx(object):
	def __enter__(self):
		global _db_ctx
		self.should_cleanup = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_cleanup = True
		return self
	def __exit__():
		global _db_ctx
		if self.should_cleanup:
			_db_ctx.cleanup()
def connection():
	return _ConnectionCtx()

class _TranscationCtx(object):
	def __enter__(self):
		global _db_ctx
		self.should_close_conn = False
		if not _db_ctx.is_init():
			_db_ctx.init()
			self.should_close_conn = True
		_db_ctx.transactions = _db_ctx.transactions + 1
		return self
	def __exit__(self,exctype,excvalue,traceback):
		global _db_ctx
		_db_ctx.transactions = _db_ctx.transactions -1
		try:
			if _db_ctx.transactions == 0:
				if exctype is None:
					self.commit()
				else:
					self.rollback()
		finally:
			if self.should_close_conn:
				_db_ctx.cleanup()
	def commit(self):
		global _db_ctx
		try:
			_db_ctx.connection.commit()
		except:
			_db_ctx.connection.rollback()
			raise
	def rollback(self):
		global _db_ctx
		_db_ctx.connection.rollback()

class DBError(Exception):
	pass
class MultiColumsError(DBError):
	pass

if __name__ == '__main__':
	logging.basicConfig(level = logging.DEBUG)
	create_engine('user', 'password', 'test', '192.168.10.128')




