from django.urls import path

from .views.users import users
from .views.pipelines import pipelines, pipeline_single
from .views.jobs import jobs
from .views.job_single import job_single_view
from .views.tasks import task_list, task_detail_view
from .views.events import event_list, event_detail_view
from .views.campaign import (
    campaign_dispatch,
    campaign_home,
    campaign_status,
    catalog_hdf5,
    reference_fits,
    reference_preview,
    reference_sources,
    target_detail,
    target_search,
)


app_name = 'manager'
urlpatterns = [
    path('users', users, name='users'),

    path('pipelines', pipelines, name='pipeline_list'),
    path('pipelines/<int:pk>', pipeline_single, name='pipeline_single'),

    path('jobs', jobs, name='jobs'),
    path('jobs/<int:pk>', job_single_view, name='job_single_view'),

    path('tasks', task_list, name='tasks'),
    path('tasks/<int:pk>', task_detail_view, name='task_detail_view'),

    path('events', event_list, name='events'),
    path('events/<int:pk>', event_detail_view, name='event_detail_view'),

    path('campaign', campaign_home, name='campaign_home'),
    path('search', target_search, name='target_search'),
    path('targets/<slug:name>', target_detail, name='target_detail'),
    path('targets/<slug:name>/status', campaign_status, name='target_status'),
    path('targets/<slug:name>/dispatch', campaign_dispatch, name='target_dispatch'),
    path('targets/<slug:name>/preview.png', reference_preview, name='target_preview'),
    path('targets/<slug:name>/sources.json', reference_sources, name='target_sources'),
    path('targets/<slug:name>/catalogs/<str:stem>.h5', catalog_hdf5, name='catalog_hdf5'),
    path('targets/<slug:name>/reference.fits', reference_fits, name='reference_fits'),
    path('st123/status', campaign_status, name='campaign_status'),
    path('st123/dispatch', campaign_dispatch, name='campaign_dispatch'),
    path('st123/preview.png', reference_preview, name='reference_preview'),
    path('st123/sources.json', reference_sources, name='reference_sources'),
]