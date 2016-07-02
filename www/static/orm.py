#!/usr/bin/env python
# -*- conding:utf-8 -*-
"""
表==>类
行==>实例
"""
import db
import time
import logging

_triggers = frozenset(['pre_insert','pre_update','pre_delete'])

def _get_sql(table_name,mappings):
	 """
    类 ==> 表时 生成创建表的sql
    """
    pk = None
    sql = ['-- generating SQL for %s:' % table_name, 'create table `%s` (' % table_name]
    for f in sorted(mappings.values(), lambda x, y: cmp(x._order, y._order)):
        if not hasattr(f, 'ddl'):
            raise StandardError('no ddl in field "%s".' % f)
        ddl = f.ddl
        nullable = f.nullable
        if f.primary_key:
            pk = f.name
        #sql.append(nullable and '  `%s` %s,' % (f.name, ddl) or '  `%s` %s not null,' % (f.name, ddl))
        sql.append('  `%s` %s,' % (f.name, ddl) if nullable else '  `%s` %s not null,' % (f.name, ddl))
    sql.append('  primary key(`%s`)' % pk)
    sql.append(');')
    return '\n'.join(sql)

class Field(object):
	"""保持数据库中的表的字段属性
    _count:类属性，没实例化一次，该值就+1
    self._order:属性，实例化时从类属性处得到，用于记录 该实例是 该类的第多少个实例

    最后生成_sql时（）这些字段就是按序排序
        create table 'user' (
        	'id' bigint not null,
        	'name' varchar(255) not null
        	'email' varchar(255) not null
        	'passwd' varchar(255) not null
        	'last_modified' real not null
        	primary key('id')
        	);
	self._default:用于让orm自己填入缺省值，缺省值可以是可调用对象，比如函数
			比如：passwd字段<StringFiled:passwd,varchar(255),default(<function <lambda> at 0x000000002a13>,UI)
				  这里passwd的默认值，就可以通过返回的函数 调用取得
	其他的实例属性都是用来描述字段属性的
    说话要冷静，说话要冷静
	"""
	_count = 0
	def __init__(self, **kw):
		self.name = kw.get('name',None)
		self._default = kw.get('default',None)
		self.primary_key = kw.get('primary_key',False)
		self.nullable = kw.get('nullable',False)
		self.updatable = kw.get('updatable',True)
		self.insertable = kw.get('insertable',True)
		self.ddl = kw.get('ddl','')
		self._order = Field._count
		Field._count += 1
	@property 
	def default(self):
		"""
		"""
		d = self._default
		return d() if callable(d) else d
	def __str__(self):
		"""
		返回实例对象的描述信息，比如
		"""
		s = ['<%s,%s,%s,default(%s),'%(self.__class__.name,self.name,self.ddl,self._default]
		self.nullable and s.append('N')
		self.updatable and s.append('U')
		self.insertable and s.append('I')
		s.append('>')
		return ''.join(s)

class StringField(Field):
	"""
	保持String类型字段属性
	"""
	def __init__(self,**kw):
		if 'default not in kw':
			kw['default'] = ''
		if 'ddl' not in kw:
			kw['ddl'] = 'varchar(255)'
		super(StringField,self).__init__(**kw)
class IntergerFild(Field):
	"""
	保持Interger类型字段属性
	"""
	def __int__(self,**kw):
		if 'default' not in kw:
			kw['default'] = 0
		if 'ddl' not in kw:
			kw['ddl'] = 'bigint'
		super(IntergerFild,self).__init__(**kw)

class FloatField(Field):
	"""
	保持Float类型字段属性
	"""
	def __int__(self,**kw):
		if 'default' not in kw:
			kw['default'] = 0.0
		if 'ddl' not in kw:
			kw['ddl'] = 'real'
		super(FloatField,self).__init__(**kw)

class BooleanField(Field):
	"""
	保持Boolean类型字段属性
	"""
	def __init__(self, **kw):
		if not 'default' in kw:
			kw['default'] = False
		if not 'ddl' in kw:
			kw['ddl'] = 'bool'
		super(BooleanField, self).__init__(**kw)

class TextField(Field):
	"""
    保持Text类型字段属性
	"""	
	def __init__(self, **kw):
		if not 'default' in kw:
			kw['default'] = ''
		if not 'ddl' in kw:
			kw['ddl'] = 'text'
		super(TextField, self).__init__(**kw)

class BlobField(Field):
	"""
	"""
	def __init__(self, **kw):
		if not 'default' in kw:
			kw['default'] = ''
		if not 'ddl' in kw:
			kw['ddl'] = 'blob'
	super(BlobField, self).__init__(**kw)

class VersionField(Field):
	"""
    保持Verison类型字段属性
	"""
	def __init__(self, name = None):
		super(VersionField, self).__init__(name = name,default = 0,ddl = 'bigint')
class ModelMetaclass(type):
	""" 
	对类对象动态完成以下操作
	避免修改Model类：
		1.排除对Model类的修改
	属性与字段的mapping:
		1.从类的属性字典中提取出，类属性和字段类的mapping
		2.提取完成后移除这些类属性，避免和实例属性冲突
		3.新增"__mappings__"属性，保持提取出的mapping数据
	类和表的mapping:
		1.提取类名，保持为表名，完成简单的类和表的映射
		2.新增"__table__"属性，保持提取出的表名
	"""
	def __new__(cls,name,bases,attrs):
		#skip base Model class
		if name == 'Model':
			return type.__new__(cls,name,bases,attrs)

		#store all subclasses info:
		if not hasattr(cls,'subclasses'):
			cls.subclasses = {}

		if not name in cls.subclasses:
			cls.subclasses[name] = name
		else :
			logging.warning('Redefine class :%s'%name)

		logging.info('Scan ORMappint%s...'%name)
		mappings = dict()
		primary_key = None
		for k,v in attrs.iteritems():
			if isinstance(v,Field):
				if not v.name:
					v.name = k
				logging.info('[MAPPING] Found mapping:%s => %s' % (k,v))
				#check duplicate primary key:
				if v.primary_key:
					if primary_key:
						raise TypeError('Cannot define more than i primary key in class :%s'%name)
					if v.updatable:
						logging.warning('NOTE:change primary key to non-updatable.')
						v.updatable = False
					if v.nullable:
						logging.warning('NOTE:change primary key to non-nullable.')
						v.nullable = False
					primary_key = v
				mappings[k] = v
		#check exist of primary key:
		if not primary_key:
			raise TypeError('Primary key not define in class :%s'% name)
		for k in mappings.iterkeys():
			attrs.pop(k)
		if not '__table__' in attrs:
			attrs['__table__'] = name.lower()
		attrs['__mappings__'] = mappings
		attrs['__primary_key__'] = primary_key
		attrs['__sql__'] = lambda self:_get_sql(attrs['__table__'],mappings)
		for trigger in _triggers:
			if not trigger in attrs:
				attrs[trigger] = None
		return type.__new__(cls,name,bases,attrs)

class Model(dict):
	""" 
	这是一个基类，用户在子类中 定义映射关系，因此我们需要动态扫描子类属性.
	从中抽取出类的属性，完成类< == > 表的映射，这里使用metaclass 来实现。
	最后将扫描出来的结果保持在
	"__table__":表名
	"__mappings__":字段对象
	"__primary_key__":主键字段
	"__sql__":创建表时候执行的sql

	子类实例化时，需要完成 实例属性 <==>行值得映射，这里使用定制dict来实现。
	Model1 从字典继承而来，并且通过"__getattr__","__setattr__"将model重写
	使得其像javascript中的object对象那样，可以通过属性访问，比如a.key = value
	"""

	__metaclass__ = ModelMetaclass
	def __int__(self,**kw):
		super(Model,self).__init__(**kw)

	def __getattr__(self,key):
		try:
			return self[key]
		except KeyError:
			raise AttributeError(r"'Dict’ object has no attribute '%s'"%key)
	def __setattr__(self,key,value):
		self[key] = value

	@classmethod
	def get(cls,pk):
		"""
		get by primary_key
		"""
		d = db.select_one('select *from %s where %s =?'%(cls.__table__,cls.__primary_key__.name),pk)
		return cls(**d) if d else None

	@classmethod
	def find_first(cls,where,*args):
		"""
		通过where语句进行条件查询，返回一个查询结果，如果有多个查询结果
		仅取第一个，如果没有结果，则返回None
		"""
		d = db.select_one('select *from %s %s' % (cls.__table__,where),*args)
		return cls(**d) if d else None

	@classmethod
	def find_all(cls,*args):
		"""
		查询所有字段，将结果从一个列表返回
		"""
		l = db.select('select *from '%s''%cls.__table__)
		return [cls(**d) for d in l]
	@classmethod
	def find_by(cls,where,*args):
		"""
		通过where语句进行条件查询，返回一个查询结果，如果有多个查询结果
		"""
		L = db.select('select * from '%s' ‘%s'%(cls.__table__,where),*args)
		return [cls(**d) for d in L)]

	@classmethod
	def count_all(cls):
		"""
		执行select count(pk) from table 语句，返回一个数值
		"""
		return db.select('select count('%s' from '%s'') %(cls.__primary_key__.name,cls.__table__))

	@classmethod
	def count_by(cls,where,*args):
		"""

		"""
		return db.select_int('select count('%s') from '%s' '%s''%(cls.__primary_key__.name,cls.__table__,where),*args)

	def update(self):
		"""
		如果该行的字段属性有updatable,代表该字段可以被更新
		用于定义表（继承Model的类）是一个Dict对象，键值会变成实例的属性
		所有可以通过属性来判断，用户是否定义了该字段的值
			如果有属性，就使用用户传入的值
			如果无属性，则调用字段对象的default属性传入

		"""
		self.pre_update and self.pre_update()
		l = []
		args = []
		for k,v in self.__mappings__.iteritems():
			if v.updatable:
				if hasattr(self,k):
					arg = getattr(self,k)
				else:
					arg = v.default
					setattr(self,k,arg)
				l.append(''%s' = ?'%k)
				args.append(arg)
		pk = self.__primary_key__.name
		args.append(getattr(self,pk))
		db.update('update '%s' set %s where %s = ?'%(self.__table__,','join(l),pk),*args)
		return self

	def delete(self):
		"""
		
		"""
		self.pre_delete and self.pre_delete()
		pk = self.__primary_key__.name
		args = (getattr(self,pk))
		db.update('delete from '%s' where '%s'=?'%(self.__table__,pk),*args)
		return self

	def insert(self):
		"""

		"""
		self.pre_insert and self.pre_insert()
		params = {}
		for k,v in self.__mappings__.iteritems():
			if v.insertable:
				if not hasattr(self,k):
					setattr(self,k,v.default)
				params[v.name] = getattr(self,k)
		db.insert('%s' % self.__table__,**params)
		return self
		
		
						
		
		