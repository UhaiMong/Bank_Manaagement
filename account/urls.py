
from django.urls import path
from .views import UserRegistrationView, UserLoginView, UserLogoutView, UserBankAccountUpdateView, PasswordChangeView

urlpatterns = [
    path('register/', UserRegistrationView.as_view(), name='register'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('profile/', UserBankAccountUpdateView.as_view(), name='profile'),
    path('change_password/', PasswordChangeView.as_view(), name='change_password')
]
