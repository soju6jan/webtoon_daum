# -*- coding: utf-8 -*-
#########################################################
# python
import os
import datetime
import traceback
import urllib
from datetime import datetime


# third-party
from sqlalchemy import desc
from sqlalchemy import or_, and_, func, not_
import requests
from lxml import html


# sjva 공용
from framework import app, db, scheduler, path_app_root, celery
from framework.job import Job
from framework.util import Util


# 패키지
from .plugin import logger, package_name
from .model import ModelSetting, ModelItem

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
    'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language' : 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer' : ''
} 



#########################################################
class LogicNormal(object):
    session = requests.Session()

    @staticmethod
    def scheduler_function():
        
        LogicNormal.scheduler_function_db()

        try:
            url = 'http://webtoon.daum.net/data/pc/webtoon/list_serialized/%s' % datetime.now().strftime('%A').lower()[0:3]
            data = requests.get(url).json()
            for item in data['data']:
                nickname = item['nickname']
                logger.debug('--- %s' % nickname)
                toon_data = LogicNormal.analysis(nickname)
                #logger.debug(toon_data)
                if toon_data['status'] != '200':
                    continue
                if not ModelSetting.get_bool('all_episode_download'):
                    LogicNormal.add(toon_data['latestEpisode'], toon_data)
                else:
                    for tmp in toon_data['episodes']:
                        LogicNormal.add(tmp, toon_data)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def add(data, toon_data):
        from .logic_queue import LogicQueue
        entity = db.session.query(ModelItem).filter_by(episode_id=data['episode_id']).first()
        if entity is None and data['price'] == 0:
            whitelists = ModelSetting.get_list('whitelist')
            if whitelists:
                flag = False
                for t in whitelists:
                    if toon_data['title'].replace(' ', '').find(t) != -1:
                        flag = True
                        logger.debug('WHITE : %s', toon_data['title'])
                        break
                if flag:
                    entity = LogicQueue.add_queue(data['episode_id'], data['episode_idx'], data['episode_title'], toon_data['title'], toon_data['nickname'])
                return
            
            blacklists = ModelSetting.get_list('blacklist') 
            if blacklists:
                for t in blacklists:
                    if toon_data['title'].replace(' ', '').find(t) != -1:
                        logger.debug('BALCK : %s', toon_data['title'])
                        return
            entity = LogicQueue.add_queue(data['episode_id'], data['episode_idx'], data['episode_title'], toon_data['title'], toon_data['nickname'])



    @staticmethod
    def scheduler_function_db():
        entities = db.session.query(ModelItem).filter(ModelItem.status<10).all()
        from .logic_queue import LogicQueue
        for e in entities:
            e.status_kor = u'대기'
            entity = LogicQueue.add_queue(e.episode_id, e.episode_idx, e.episode_title, e.toon_title, e.toon_nickname)


    @staticmethod
    def get_html(url, referer=None, stream=False):
        try:
            if LogicNormal.session is None:
                LogicNormal.session = requests.session()
            #logger.debug('get_html :%s', url)
            headers['Referer'] = '' if referer is None else referer
            page_content = LogicNormal.session.get(url, headers=headers)
            data = page_content.content
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
        return data

    @staticmethod
    def entity_update(entity):
        import plugin
        plugin.socketio_callback('queue_one', entity, encoding=False)
    

    @staticmethod
    def download(entity):
        try:
            entity['download_count'] += 1
            entity['status'] = 1
            entity['str_status'] = '대기'
            LogicNormal.entity_update(entity)

            url = 'http://webtoon.daum.net/data/pc/webtoon/viewer_images/%s' % (entity['episode_id'])
            data = requests.get(url).json()

            entity['str_status'] = '분석'
            LogicNormal.entity_update(entity)

            dirname = ModelSetting.get('download_path')
            if ModelSetting.get_bool('use_title_folder'):
                dirname = os.path.join(dirname, Util.change_text_for_use_filename(entity['toon_title']))
            #if not os.path.exists(dirname):
            #    os.makedirs(dirname)

            tmp = u'%s %s %s' % (entity['episode_idx'].zfill(3), entity['toon_title'], entity['episode_title'])
            dirname = os.path.join(dirname, Util.change_text_for_use_filename(tmp))
            if not os.path.exists(dirname):
                os.makedirs(dirname)
                
            entity['filename'] = '%s.zip' % dirname

            if os.path.exists(entity['filename']):
                entity['status'] = 12
                entity['str_status'] = '파일 있음'
                LogicNormal.entity_update(entity)
            else:    
                entity['str_status'] = '다운로드중'
                LogicNormal.entity_update(entity)
                count = len(data['data'])
                for idx, tmp in enumerate(data['data']):
                    filename = os.path.join(dirname, str(idx+1).zfill(2) + '.jpg')
                    image_data = requests.get(tmp['url'], headers=headers, stream=True)
                    with open(filename, 'wb') as handler:
                        handler.write(image_data.content)
                    entity['str_status'] = '다운로드중 %s / %s' % (idx+1, count)
                    entity['percent'] = int(100.0 * (idx+1) / count)
                    LogicNormal.entity_update(entity)
                Util.makezip(dirname)
                entity['status'] = 11
                entity['str_status'] = '완료'
                LogicNormal.entity_update(entity)
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            entity['status'] = 2
            entity['str_status'] = '실패'
            if entity['download_count'] >= 5:
                entity['status'] = 13
                entity['str_status'] = '재시도초과'
            LogicNormal.entity_update(entity)
        ModelItem.save_as_dict(entity)                

    
    @staticmethod
    def analysis(nickname):
        ret = {}
        try:
            url = 'http://webtoon.daum.net/data/pc/webtoon/view/%s' % (nickname)
            data = requests.get(url).json()
            #logger.debug(data)
            ret['status'] = data['result']['status']
            if ret['status'] != '200':
                ret['ret'] = 'error'
                ret['log'] = data['result']['message']
                return ret

            ret['title'] = data['data']['webtoon']['title']
            ret['nickname'] = data['data']['webtoon']['nickname']
            ret['id'] = data['data']['webtoon']['id']
            ret['image'] = data['data']['webtoon']['pcThumbnailImage']['url']
            ret['desc'] = data['data']['webtoon']['introduction']
            try:
                ret['author'] = data['data']['webtoon']['cp']['name']
            except:
                ret['author'] = ''

            ret['episodes'] = []
            for epi in data['data']['webtoon']['webtoonEpisodes']:
                try:
                    entity = {}
                    entity['episode_id'] = epi['id']
                    entity['episode_idx'] = epi['episode']
                    entity['episode_title'] = epi['title']
                    entity['image'] = epi['thumbnailImage']['url']
                    entity['price'] = epi['price']
                    entity['date'] = '%s-%s-%s' % (epi['dateCreated'][:4], epi['dateCreated'][4:6], epi['dateCreated'][6:8])
                    ret['episodes'].append(entity)
                except:
                    pass
            ret['latestEpisode'] = {'episode_id':data['data']['webtoon']['latestWebtoonEpisode']['id'], 'episode_idx':data['data']['webtoon']['latestWebtoonEpisode']['episode'], 'episode_title':data['data']['webtoon']['latestWebtoonEpisode']['title'], 'price':data['data']['webtoon']['latestWebtoonEpisode']['price']}

            ret['ret'] = 'success'

            LogicNormal.current_data = data
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['log'] = str(e)
        return ret    