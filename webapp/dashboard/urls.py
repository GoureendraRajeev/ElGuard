from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/overview/", views.overview, name="overview"),
    path("api/forecast/<slug:state>/", views.forecast, name="forecast"),
    path("api/climate/<slug:state>/", views.climate, name="climate"),
    path("api/geojson/<slug:state>/", views.geojson, name="geojson"),
]
