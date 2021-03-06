import json
from datetime import datetime

from django.contrib.auth.models import User

from nose.tools import eq_

import amo
from addons.models import AddonCategory, AddonDeviceType, Category
from amo.tests import ESTestCase
import mkt.regions
from mkt.api.base import list_url
from mkt.api.models import Access, generate
from mkt.api.tests.test_oauth import BaseOAuth, OAuthClient
from mkt.search.forms import DEVICE_CHOICES_IDS
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestApi(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.client = OAuthClient(None)
        self.list_url = ('api_dispatch_list', {'resource_name': 'search'})
        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        self.webapp.save()
        self.refresh()

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ['get'])

    def test_has_cors(self):
        res = self.client.get(self.list_url)
        eq_(res['Access-Control-Allow-Origin'], '*')
        eq_(res['Access-Control-Allow-Methods'], 'GET, OPTIONS')

    def test_meta(self):
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(set(data.keys()), set(['objects', 'meta']))
        eq_(data['meta']['total_count'], 1)

    def test_wrong_category(self):
        res = self.client.get(self.list_url + ({'cat': self.category.pk + 1},))
        eq_(res.status_code, 400)
        eq_(res['Content-Type'], 'application/json')

    def test_wrong_weight(self):
        self.category.update(weight=-1)
        res = self.client.get(self.list_url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 0)

    def test_wrong_sort(self):
        res = self.client.get(self.list_url + ({'sort': 'awesomeness'},))
        eq_(res.status_code, 400)

    def test_right_category(self):
        res = self.client.get(self.list_url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['objects'], [])

    def create(self):
        AddonCategory.objects.create(addon=self.webapp, category=self.category)
        self.webapp.save()
        self.refresh()

    def test_right_category_present(self):
        self.create()
        res = self.client.get(self.list_url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 1)

    def test_dehydrate(self):
        with self.settings(SITE_URL=''):
            self.create()
            res = self.client.get(self.list_url + ({'cat': self.category.pk},))
            eq_(res.status_code, 200)
            obj = json.loads(res.content)['objects'][0]
            eq_(obj['slug'], self.webapp.app_slug)
            eq_(obj['icons']['128'], self.webapp.get_icon_url(128))
            eq_(obj['absolute_url'], self.webapp.get_absolute_url())
            eq_(obj['resource_uri'], None)

    def test_q(self):
        res = self.client.get(self.list_url + ({'q': 'something'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_device(self):
        AddonDeviceType.objects.create(
            addon=self.webapp, device_type=DEVICE_CHOICES_IDS['desktop'])
        self.webapp.save()
        self.refresh()
        res = self.client.get(self.list_url + ({'device': 'desktop'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_premium_types(self):
        res = self.client.get(self.list_url + (
            {'premium_types': 'free'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_premium_types_empty(self):
        res = self.client.get(self.list_url + (
            {'premium_types': 'premium'},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)

    def test_multiple_premium_types(self):
        res = self.client.get(self.list_url + (
            {'premium_types': 'free'},
            {'premium_types': 'premium'}))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_app_type_hosted(self):
        res = self.client.get(self.list_url + ({'app_type': 'hosted'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_app_type_packaged(self):
        self.webapp.update(is_packaged=True)
        self.webapp.save()
        self.refresh()

        res = self.client.get(self.list_url + ({'app_type': 'packaged'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_status_anon(self):
        res = self.client.get(self.list_url + ({'status': 'public'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.list_url + ({'status': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = json.loads(res.content)['error_message']
        eq_(error.keys(), ['status'])

        res = self.client.get(self.list_url + ({'status': 'any'},))
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'],
            'Unauthorized to filter by status.')

        res = self.client.get(self.list_url + ({'status': 'rejected'},))
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'],
            'Unauthorized to filter by status.')

    def test_status_value_packaged(self):
        # When packaged and not a reviewer we exclude latest version status.
        self.webapp.update(is_packaged=True)
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['status'], amo.STATUS_PUBLIC)
        eq_('latest_version_status' in obj, False)

    def test_addon_type_anon(self):
        res = self.client.get(self.list_url + ({'type': 'app'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.list_url + ({'type': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = json.loads(res.content)['error_message']
        eq_(error.keys(), ['type'])

        res = self.client.get(self.list_url + ({'type': 'persona'},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)


class TestApiReviewer(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self, api_name='apps'):
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.profile.update(read_dev_agreement=datetime.now())
        self.grant_permission(self.profile, 'Apps:Review')

        self.access = Access.objects.create(key='foo', secret=generate(),
                                            user=self.user)
        self.client = OAuthClient(self.access, api_name=api_name)
        self.list_url = ('api_dispatch_list', {'resource_name': 'search'})

        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        self.webapp.save()
        self.refresh()

    def test_status_reviewer(self):
        res = self.client.get(self.list_url + ({'status': 'public'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.list_url + ({'status': 'rejected'},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.list_url + ({'status': 'any'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.list_url + ({'status': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = json.loads(res.content)['error_message']
        eq_(error.keys(), ['status'])

    def test_status_value_packaged(self):
        # When packaged we also include the latest version status.
        self.webapp.update(is_packaged=True)
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['status'], amo.STATUS_PUBLIC)
        eq_(obj['latest_version_status'], amo.STATUS_PUBLIC)

    def test_addon_type_reviewer(self):
        res = self.client.get(self.list_url + ({'type': 'app'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.list_url + ({'type': 'persona'},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.list_url + ({'type': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = json.loads(res.content)['error_message']
        eq_(error.keys(), ['type'])


class TestCategoriesWithCreatured(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141', 'user_2519')
    list_url = list_url('search/creatured')

    def test_creatured_plus_category(self):
        cat = Category.objects.create(type=amo.ADDON_WEBAPP, slug='shiny')
        app2 = amo.tests.app_factory()
        AddonCategory.objects.get_or_create(addon=app2, category=cat)
        AddonCategory.objects.get_or_create(addon_id=337141, category=cat)
        self.make_featured(app=app2, category=cat,
                           region=mkt.regions.US)

        self.refresh()
        res = self.client.get(self.list_url + ({'cat': 'shiny'},))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)
        eq_(len(data['creatured']), 1)
        eq_(int(data['creatured'][0]['id']), app2.pk)

    def test_no_category(self):
        cat = Category.objects.create(type=amo.ADDON_WEBAPP, slug='shiny')
        app = amo.tests.app_factory()
        AddonCategory.objects.get_or_create(addon=app, category=cat)
        self.make_featured(app=app, category=cat,
                           region=mkt.regions.US)

        self.refresh()
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)
        eq_(len(data['creatured']), 0)
