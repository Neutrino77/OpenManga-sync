from datetime import datetime

from flask import json
from flask_restful import Resource, reqparse, marshal_with

from app import db, log
from common.auth import auth_required
from common.models import History, Manga, Deleted
from common.schemas import history_schema, base_schema

parser = reqparse.RequestParser()
parser.add_argument('updated')
parser.add_argument('deleted')
parser.add_argument('id', type=int)


class HistoryApi(Resource):
	# get all history
	@marshal_with(history_schema)
	@auth_required
	def get(self, token):
		try:
			history = History.query.filter(History.user_id == token.user_id).all()
			return {'all': history}
		except Exception as e:
			log.error(e)
			return {'state': 'fail', 'message': str(e)}, 500

	# data synchronization - post and get updates
	@marshal_with(history_schema)
	@auth_required
	def post(self, token):
		try:
			args = parser.parse_args()
			user = token.user
			last_sync = token.last_sync_history
			history = History.query.filter(History.user_id == user.id)
			if last_sync is not None:
				history = history.filter(History.updated_at > last_sync)
			updated = history.all()

			deleted = Deleted.query.filter(Deleted.subject == 'history', Deleted.user_id == user.id)
			if last_sync is not None:
				deleted = deleted.filter(Deleted.deleted_at > last_sync)
			deleted = deleted.all()

			client_updated = json.loads(args['updated'])

			for item in client_updated:
				item['updated_at'] = datetime.fromtimestamp(item['timestamp'] / 1000.0)
				item.pop('timestamp', None)
				obj = History(**item)
				obj.manga = Manga(**item['manga'])
				obj.user_id = user.id
				obj.manga_id = obj.manga.id
				manga = Manga.query.get(obj.manga_id)
				if manga is None:
					db.session.add(obj.manga)
					db.session.flush()
				hist = History.query.filter(History.manga_id == obj.manga_id, History.user_id == obj.user_id).first()
				if hist is None:
					db.session.add(obj)
				else:
					hist.chapter = obj.chapter
					hist.page = obj.page
					hist.size = obj.size
					hist.isweb = obj.isweb
					hist.updated_at = obj.updated_at
				db.session.flush()

			client_deleted = json.loads(args['deleted'])
			for item in client_deleted:
				item['deleted_at'] = datetime.fromtimestamp(item['timestamp'] / 1000.0)
				item.pop('timestamp', None)
				obj = Deleted(**item)
				obj.user_id = user.id
				obj.subject = 'history'
				udeleted = Deleted.query.filter(Deleted.manga_id == obj.manga_id, Deleted.user_id == obj.user_id).first()
				if udeleted is None:
					db.session.add(obj)
				else:
					udeleted.deleted_at = obj.deleted_at
				db.session.flush()
				History.query.filter(History.manga_id == obj.manga_id, History.user_id == obj.user_id).delete()

				db.session.flush()

			token.last_sync_history = datetime.now()
			db.session.flush()
			db.session.commit()
			return {'updated': updated, 'deleted': deleted}
		except Exception as e:
			db.session.rollback()
			log.exception(e)
			return {'state': 'fail', 'message': str(e)}, 500

	# delete one item from history
	@marshal_with(base_schema)
	@auth_required
	def delete(self, token):
		try:
			args = parser.parse_args()
			user = token.user
			manga_id = args['id']

			deleted = History.query.filter(History.manga_id == manga_id).delete()
			if deleted > 0:
				obj = Deleted()
				obj.manga_id = manga_id
				obj.user_id = user.id
				obj.subject = 'history'
				obj.deleted_at = datetime.now()
				db.session.add(obj)

			db.session.flush()
			db.session.commit()
		except Exception as e:
			log.exception(e)
			db.session.rollback()
			return {'state': 'fail', 'message': str(e)}, 500