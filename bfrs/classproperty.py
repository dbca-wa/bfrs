class ClassPropertyDescriptor(object):

    #def __init__(self, fget, fset=None):
    def __init__(self, fget):
        self.fget = fget
        #self.fset = fset

    def __get__(self, obj, klass=None):
        if klass is None:
            klass = type(obj)
        return self.fget.__get__(obj, klass)()
    """
    def __set__(self, obj, value):
        if not self.fset:
            raise AttributeError("can't set attribute")
        type_ = type(obj)
        return self.fset.__get__(obj, type_)(value)

    def setter(self, func):
        import ipdb;ipdb.set_trace()
        if not isinstance(func, (classmethod, staticmethod)):
            func = classmethod(func)
        self.fset = func
        return self
    """

def classproperty(func):
    if not isinstance(func, (classmethod, staticmethod)):
        func = classmethod(func)

    return ClassPropertyDescriptor(func)

class CachedClassPropertyDescriptor(object):

    def __init__(self, fget):
        self.fget = fget

    def __get__(self, obj, klass=None):
        if klass is None:
            klass = type(obj)
        try:
            return self.cached_data
        except:
            self.cached_data = self.fget.__get__(obj, klass)()
            return self.cached_data

def cachedclassproperty(func):
    if not isinstance(func, (classmethod, staticmethod)):
        func = classmethod(func)

    return CachedClassPropertyDescriptor(func)
"""
class Test(object):
    @classproperty
    def NAME1(cls):
        print("CALL 'Test.NAME1'")
        return cls._NAME1 if hasattr(cls,"_NAME1") else "Jack1" 

    @classproperty
    def NAME2(cls):
        print("CALL 'Test.NAME2'")
        return cls._NAME2 if hasattr(cls,"_NAME2") else "Jack2" 


    @cachedclassproperty
    def CACHED_NAME1(cls):
        print("CALL 'Test.CACHED_NAME1'")
        return cls._CACHED_NAME1 if hasattr(cls,"_CACHED_NAME1") else "Cached Jack1" 

    @cachedclassproperty
    def CACHED_NAME2(cls):
        print("CALL 'Test.CACHED_NAME2'")
        return cls._CACHED_NAME2 if hasattr(cls,"_CACHED_NAME2") else "Cached Jack2" 

    @cachedclassproperty
    def CACHED_NAME3(cls):
        print("CALL 'Test.CACHED_NAME3'")
        return cls._CACHED_NAME3 if hasattr(cls,"_CACHED_NAME3") else "Cached Jack3" 

class Test1(Test):
    @classproperty
    def NAME2(cls):
        print("CALL 'Test1.NAME2'")
        return cls._NAME2 if hasattr(cls,"_NAME2") else "Tommy2" 


    @cachedclassproperty
    def CACHED_NAME2(cls):
        print("CALL 'Test1.CACHED_NAME2'")
        return cls._CACHED_NAME2 if hasattr(cls,"_CACHED_NAME2") else "Cached Tommy2" 

    @classproperty
    def CACHED_NAME3(cls):
        print("CALL 'Test1.CACHED_NAME3'")
        return cls._CACHED_NAME3 if hasattr(cls,"_CACHED_NAME3") else "Cached Tommy3" 

The setter didn't work at the time we call Bar.bar, because we are calling TypeOfBar.bar.__set__, which is not Bar.bar.__set__.

Adding a metaclass definition solves this:

class ClassPropertyMetaClass(type):
    def __setattr__(self, key, value):
        if key in self.__dict__:
            obj = self.__dict__.get(key)
        if obj and type(obj) is ClassPropertyDescriptor:
            return obj.__set__(self, value)

        return super(ClassPropertyMetaClass, self).__setattr__(key, value)

# and update class define:
#     class Bar(object):
#        __metaclass__ = ClassPropertyMetaClass
#        _bar = 1

# and update ClassPropertyDescriptor.__set__
#    def __set__(self, obj, value):
#       if not self.fset:
#           raise AttributeError("can't set attribute")
#       if inspect.isclass(obj):
#           type_ = obj
#           obj = None
#       else:
#           type_ = type(obj)
#       return self.fset.__get__(obj, type_)(value)
"""

