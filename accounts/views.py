from django.contrib.auth import authenticate, login, logout
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class LoginAPI(APIView):
    """POST {username, password} → session cookie (+ optional token)."""
    permission_classes = [AllowAny]
    authentication_classes = []  # skip CSRF enforcement for this JSON endpoint

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        password = request.data.get('password') or ''
        # allow login with email as username
        if '@' in username:
            from django.contrib.auth.models import User
            u = User.objects.filter(email__iexact=username).first()
            if u:
                username = u.username
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({'detail': 'Invalid username or password.'},
                            status=status.HTTP_401_UNAUTHORIZED)
        login(request, user)
        from rest_framework.authtoken.models import Token
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'username': user.username,
            'email': user.email,
            'is_staff': user.is_staff,
            'token': token.key,
        })


class LogoutAPI(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        logout(request)
        return Response({'detail': 'Logged out.'})


class MeAPI(APIView):
    def get(self, request):
        u = request.user
        return Response({
            'username': u.username,
            'email': u.email,
            'is_staff': u.is_staff,
            'is_superuser': u.is_superuser,
        })
