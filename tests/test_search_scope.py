import pytest
from urllib.parse import parse_qs, urlsplit
from app.search_scope import IT_ROLES, remote_it_filters, remote_it_url, remote_it_rejection, vacancy_scope_rejection


def test_filters_replace_non_remote_conditions_but_keep_query():
    source={'schedule':['fullDay','remote'], 'work_format':'HYBRID', 'professional_role':'1',
            'text':'python', 'area':['1','2']}
    result=remote_it_filters(source)
    assert result['schedule']=='remote' and result['work_format']=='REMOTE'
    assert set(result['professional_role'])==IT_ROLES
    assert result['text']=='python' and result['area']==['1','2']
    assert source['professional_role']=='1'


def test_web_query_is_encoded_without_losing_regions_or_page():
    q=parse_qs(urlsplit(remote_it_url('https://hh.ru/search/vacancy?text=python&area=1&area=2&page=9&schedule=fullDay')).query)
    assert q['schedule']==['remote'] and q['work_format']==['REMOTE']
    assert q['area']==['1','2'] and q['page']==['9']
    assert set(q['professional_role'])==IT_ROLES


@pytest.mark.parametrize('roles,formats,schedule,expected', [
    ([{'id':'96'}],[{'id':'REMOTE'}],None,None),
    ([{'id':'124'}],[{'id':'HYBRID'},{'id':'REMOTE'}],None,None),
    ([{'id':'96'}],[{'id':'HYBRID'}],{'id':'remote'},'not_remote'),
    ([{'id':'96'}],None,{'id':'remote'},None),
    ([{'id':'96'}],None,{'id':'fullDay'},'not_remote'),
    ([{'id':'1'}],[{'id':'REMOTE'}],None,'not_it'),
    (None,[{'id':'REMOTE'}],None,'scope_unknown'),
    ([{'id':'96'}],None,None,'scope_unknown'),
])
def test_only_confirmed_remote_it_is_eligible(roles,formats,schedule,expected):
    assert remote_it_rejection({'professional_roles':roles,'work_format':formats,'schedule':schedule})==expected


def test_global_setting_applies_to_every_mobile_query(monkeypatch):
    from app.manager import _mobile_search_filters
    monkeypatch.setattr('app.manager.CONFIG.remote_it_only', True)
    for source in ({}, {'schedule':'fullDay'}, {'professional_role':'1','text':'test'}):
        result=_mobile_search_filters(source)
        assert result['work_format']=='REMOTE'
        assert set(result['professional_role'])==IT_ROLES


def test_worldwide_search_omits_area_in_actual_mobile_request(monkeypatch):
    from app.manager import parse_search_url
    from app.mobile_search import search_vacancies
    url=remote_it_url('https://hh.ru/search/vacancy?order_by=publication_time')
    text,area,filters=parse_search_url(url)
    assert text=='' and area is None
    calls=[]
    def request(acc,method,endpoint,params):
        calls.append(dict(params))
        assert 'area' not in params
        assert params['text']==''
        assert set(params['professional_role'])==IT_ROLES
        return {'pages':0,'items':[]}
    monkeypatch.setattr('app.mobile_search.mobile_request',request)
    search_vacancies({},text,area_id=area,filters=filters)
    assert len(calls)==1


def test_enabled_location_modes_are_an_or_union():
    assert vacancy_scope_rejection(
        {'country_id': '155'}, local_country_only=True, local_country_id='155',
    ) is None
    assert vacancy_scope_rejection(
        {'country_id': '1001'}, relocation_country_only=True, relocation_country_ids=['1001'],
    ) is None
