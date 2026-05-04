from django.urls import path
from .views import home, register, restaurant_dashboard,add_food,close_day,predict_page,request_food,accept_request, reject_request,request_status,delete_request,delete_all_requests, update_location, wedding_donation
from django.contrib.auth import views as auth_views


urlpatterns = [
    path("", home, name="home"), # iOpens home page 
    path("register/", register, name="register"), # opens register page
    path("dashboard/", restaurant_dashboard, name="restaurant_dashboard"), # /dashboard -- opens dashboard 
    path('add-food/', add_food, name='add_food'),
    path('close_day/',close_day,name='close_day'),
    path("logout/", auth_views.LogoutView.as_view(next_page='home'), name="logout"),
    path("predict/", predict_page, name="predict_page"),
    path("wedding-donation/", wedding_donation, name="wedding_donation"),
    path("update-location/", update_location, name="update_location"),
    path("request-food/<str:restaurant_username>/", request_food, name="request_food"),
    path("request/accept/<int:req_id>/", accept_request, name="accept_request"),
    path("request/reject/<int:req_id>/", reject_request, name="reject_request"),
    path("request-status/<int:req_id>/", request_status, name="request_status"),
    path("delete-request/<int:req_id>/", delete_request, name="delete_request"),
    path("delete-all-requests/", delete_all_requests, name="delete_all_requests"),



]
