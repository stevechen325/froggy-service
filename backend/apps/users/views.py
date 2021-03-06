import requests
import environ
import datetime

from uuid import uuid4

from django.http import JsonResponse
from django.contrib.auth import authenticate, login
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError

from django.core.signing import TimestampSigner, BadSignature

from apps.users.models import User
from apps.files.models import TempFile
from apps.users.serializers import UserSerializer, UserWriteSerializer
from apps.users.utils import jwt_payload_handler, jwt_encode_handler


env = environ.Env()


API_VERSION = env.str('VUE_APP_ACCOUNTKIT_VERSION')
ACCOUNTKIT_SECRET = env.str('VUE_APP_ACCOUNTKIT_APP_SECRET')
ACCOUNTKIT_APP_ID = env.str('VUE_APP_ACCOUNTKIT_APP_ID')
FILE_LIMIT_CASE = settings.FILE_LIMIT_CASE


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ['get', 'post', 'put', 'retrieve']

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return UserSerializer
        return UserWriteSerializer

    def perform_create(self, serializer):
        user = serializer.save()
        user.set_password(self.request.data.get('password'))
        user.save()

    def perform_update(self, serializer):
        user = serializer.save()
        if 'password' in self.request.data:
            user.set_password(self.request.data.get('password'))
            user.save()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save()

    @action(methods=['GET'], detail=True)
    def profile(self, request):
        if request.user.is_authenticated:
            serializer = self.serializer_class(request.user)
            return Response(status=status.HTTP_200_OK, data=serializer.data)
        return Response(status=status.HTTP_401_UNAUTHORIZED)

    @action(methods=['POST'], detail=False)
    def login(self, request, format=None):
        email = request.data.get('email', None)
        password = request.data.get('password', None)
        user = authenticate(username=email, password=password)

        if user:
            login(request, user)
            return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_404_NOT_FOUND)

    @action(methods=['POST'], detail=False)
    def register(self, request):
        last_name = request.data.get('last_name', None)
        first_name = request.data.get('first_name', None)
        email = request.data.get('email', None)
        password = request.data.get('password', None)

        if User.objects.filter(email__iexact=email).exists():
            return Response({'status': 210})

        # user creation
        user = User.objects.create(
            email=email,
            password=password,
            last_name=last_name,
            first_name=first_name,
        )
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @action(methods=['POST'], detail=False)
    def password_reset(self, request, format=None):
        if User.objects.filter(email=request.data['email']).exists():
            user = User.objects.get(email=request.data['email'])
            params = {'user': user, 'DOMAIN': settings.DOMAIN}
            send_mail(
                subject='Password reset',
                message=render_to_string('mail/password_reset.txt', params),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[request.data['email']],
            )
            return Response(status=status.HTTP_200_OK)
        else:
            return Response(status=status.HTTP_404_NOT_FOUND)

    @action(methods=['POST'], detail=False)
    def password_change(self, request, format=None):
        if User.objects.filter(token=request.data['token']).exists():
            user = User.objects.get(token=request.data['token'])
            user.set_password(request.data['password'])
            user.token = uuid4()
            user.save()
            return Response(status=status.HTTP_200_OK)
        else:
            return Response(status=status.HTTP_404_NOT_FOUND)

    @action(methods=['POST'], detail=False, permission_classes=[])
    def accountkit_get_token(self, request):
        code = request.data.get('code')
        state = request.data.get('state')
        status_ = request.data.get('status')

        if status_ != "PARTIALLY_AUTHENTICATED":
            raise AuthenticationFailed('AccountKit not authenticated.')

        try:
            signer = TimestampSigner()
            # unsign csrf token
            signer.unsign(state)
        except BadSignature:
            raise PermissionDenied('CSRF Failed: token not valid.')

        # Exchange authorization code for access token
        token_url = f'https://graph.accountkit.com/{API_VERSION}/access_token'
        params = {
            'grant_type': 'authorization_code',
            'code': code,
            'access_token': f'AA|{ACCOUNTKIT_APP_ID}|{ACCOUNTKIT_SECRET}',
        }

        res = requests.get(token_url, params=params)
        token_response = res.json()

        if 'error' in token_response:
            raise AuthenticationFailed(f'This authorization code has been used.{token_response["error"]}')

        user_access_token = token_response.get('access_token')

        # Get Account Kit information
        identity_url = f'https://graph.accountkit.com/{API_VERSION}/me'
        identity_params = {'access_token': user_access_token}

        res = requests.get(identity_url, params=identity_params)
        identity_response = res.json()

        if 'error' in identity_response:
            error_message = identity_response['error']['message']
            raise AuthenticationFailed(error_message)

        elif identity_response['application']['id'] != ACCOUNTKIT_APP_ID:
            raise AuthenticationFailed('The application id returned does not match the one in your settings.')

        user = None
        email = None
        mobile = None
        if 'email' in identity_response:
            email = identity_response['email']['address']
            user = User.objects.filter(email=email).first()
        elif 'phone' in identity_response:
            if identity_response['phone']['country_prefix'] != '886':
                raise ValidationError('請使用國碼為+886的手機進行驗證')
            mobile = '0' + identity_response['phone']['national_number']
            user = User.objects.filter(mobile=mobile).first()

        if not user:
            # Register a new account kit user
            user = User.objects.create_accountkit_user(email=email, mobile=mobile, full_name='AccountKit User')

        objs = TempFile.objects.filter(user=user, upload_time__date=datetime.date.today())
        if objs.distinct('case_uuid').count() >= FILE_LIMIT_CASE:
            raise ValidationError('您的手機號碼已超出每日服務驗證次數限制，請聯絡本團隊為您處理')

        payload = jwt_payload_handler(user)
        jwt = jwt_encode_handler(payload)

        return JsonResponse({
            'email': email,
            'mobile': mobile,
            'jwt': jwt,
        })
