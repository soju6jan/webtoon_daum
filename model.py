# -*- coding: utf-8 -*-
#########################################################
# python
import traceback
from datetime import datetime
import json
import os

# third-party
from sqlalchemy import or_, and_, func, not_, desc
from sqlalchemy.orm import backref

# sjva 공용
from framework import app, db, path_app_root
from framework.util import Util

# 패키지
from .plugin import logger, package_name
from downloader import ModelDownloaderItem

app.config['SQLALCHEMY_BINDS'][package_name] = 'sqlite:///%s' % (os.path.join(path_app_root, 'data', 'db', '%s.db' % package_name))
#########################################################
        
class ModelSetting(db.Model):
    __tablename__ = '%s_setting' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String, nullable=False)
 
    def __init__(self, key, value):
        self.key = key
        self.value = value

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        return {x.name: getattr(self, x.name) for x in self.__table__.columns}

    @staticmethod
    def get(key):
        try:
            return db.session.query(ModelSetting).filter_by(key=key).first().value.strip()
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def get_int(key):
        try:
            return int(ModelSetting.get(key))
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def get_bool(key):
        try:
            return (ModelSetting.get(key) == 'True')
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())

    @staticmethod
    def set(key, value):
        try:
            item = db.session.query(ModelSetting).filter_by(key=key).with_for_update().first()
            if item is not None:
                item.value = value.strip()
                db.session.commit()
            else:
                db.session.add(ModelSetting(key, value.strip()))
        except Exception as e:
            logger.error('Exception:%s %s', e, key)
            logger.error(traceback.format_exc())

    @staticmethod
    def to_dict():
        try:
            from framework.util import Util
            return Util.db_list_to_dict(db.session.query(ModelSetting).all())
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def setting_save(req):
        try:
            for key, value in req.form.items():
                if key in ['scheduler', 'is_running']:
                    continue
                if key.startswith('tmp_'):
                    continue
                logger.debug('Key:%s Value:%s', key, value)
                entity = db.session.query(ModelSetting).filter_by(key=key).with_for_update().first()
                entity.value = value
            db.session.commit()
            return True                  
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            logger.debug('Error Key:%s Value:%s', key, value)
            return False

    @staticmethod
    def get_list(key):
        try:
            value = ModelSetting.get(key)
            values = [x.strip().replace(' ', '').strip() for x in value.replace('\n', '|').split('|')]
            values = Util.get_list_except_empty(values)
            return values
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            logger.error('Error Key:%s Value:%s', key, value)




class ModelItem(db.Model):
    __tablename__ = '%s_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    json = db.Column(db.JSON)
    created_time = db.Column(db.DateTime)

    inqueue_time = db.Column(db.DateTime)
    status = db.Column(db.Integer) # 0:생성, 1:요청, 2:실패 11완료 12:파일잇음
    str_status = db.Column(db.String)

    episode_id = db.Column(db.String) # 고유값
    episode_idx = db.Column(db.String) # 툰에서의 index
    episode_title = db.Column(db.String)
    toon_title = db.Column(db.String)
    toon_nickname = db.Column(db.String)

    download_count = db.Column(db.Integer) #시도 횟수
    filename = db.Column(db.String)

    def __init__(self, episode_id, episode_idx, episode_title, toon_title, toon_nickname):
        self.created_time = datetime.now()
        self.download_count = 0

        self.episode_id = episode_id
        self.episode_idx = episode_idx
        self.episode_title = episode_title
        self.toon_title = toon_title
        self.toon_nickname = toon_nickname
        self.status = 0
        self.str_status = u'대기'

    def as_dict(self):
        ret = {x.name: getattr(self, x.name) for x in self.__table__.columns}
        ret['created_time'] = self.created_time.strftime('%m-%d %H:%M:%S') 
        ret['inqueue_time'] = self.inqueue_time.strftime('%m-%d %H:%M:%S') if self.inqueue_time is not None else None
        ret['percent'] = 0 if self.status in [0, 1, 2] else 100
        return ret

    @staticmethod
    def init(episode_id, episode_idx, episode_title, toon_title, toon_nickname):
        try:
            entity = db.session.query(ModelItem).filter_by(episode_id=episode_id).first()
            if entity is None:
                entity = ModelItem(episode_id, episode_idx, episode_title, toon_title, toon_nickname)
                entity.inqueue_time = datetime.now()
                db.session.add(entity)
                db.session.commit()
            return entity.as_dict()
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def save_as_dict(d):
        try:
            #logger.debug(d)
            entity = db.session.query(ModelItem).filter_by(id=d['id']).with_for_update().first()
            if entity is not None:
                entity.status = d['status']
                entity.str_status = unicode(d['str_status'])
                #entity.title_id = d['title_id']
                #entity.episode_id = d['episode_id']
                #entity.title = unicode(d['title'])
                #entity.episode_title = unicode(d['episode_title'])
                entity.download_count = d['download_count']
                entity.filename = d['filename']
                db.session.commit()
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_list(by_dict=False):
        try:
            tmp = db.session.query(ModelItem).all()
            if by_dict:
                tmp = [x.as_dict() for x in tmp]
            return tmp
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    
    @staticmethod
    def select(req):
        try:
            class_is = ModelItem
            ret = {}
            page = 1
            page_size = 30
            job_id = ''
            search = ''
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word'].strip()
            query = db.session.query(class_is)
            if search != '':
                query = query.filter(class_is.toon_title.like('%'+search+'%'))
            query = query.order_by(desc(class_is.id))
            count = query.count()
            query = query.limit(page_size).offset((page-1)*page_size)
            lists = query.all()
            ret['list'] = [item.as_dict() for item in lists]
            ret['paging'] = Util.get_paging_info(count, page, page_size)
            return ret
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def delete(req):
        try:
            class_is = ModelItem
            db_id = int(req.form['id'])
            item = db.session.query(class_is).filter_by(id=db_id).first()
            if item is not None:
                db.session.delete(item)
                db.session.commit()
            return True
        except Exception, e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return False
