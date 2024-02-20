# Avoid shadowing the login() and logout() views below.
from bolt.auth import USER_HASH_SESSION_KEY, get_user_model
from bolt.auth import login as auth_login
from bolt.auth.views import AuthViewMixin
from bolt.exceptions import ImproperlyConfigured, ValidationError
from bolt.http import (
    ResponseRedirect,
)
from bolt.runtime import settings
from bolt.urls import NoReverseMatch, reverse, reverse_lazy
from bolt.utils.cache import add_never_cache_headers
from bolt.utils.functional import Promise
from bolt.utils.http import urlsafe_base64_decode
from bolt.views import FormView, TemplateView

from .forms import (
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
)
from .tokens import default_token_generator


def resolve_url(to, *args, **kwargs):
    """
    Return a URL appropriate for the arguments passed.

    The arguments could be:

        * A model: the model's `get_absolute_url()` function will be called.

        * A view name, possibly with arguments: `urls.reverse()` will be used
          to reverse-resolve the name.

        * A URL, which will be returned as-is.
    """
    # If it's a model, use get_absolute_url()
    if hasattr(to, "get_absolute_url"):
        return to.get_absolute_url()

    if isinstance(to, Promise):
        # Expand the lazy instance, as it can cause issues when it is passed
        # further to some Python functions like urlparse.
        to = str(to)

    # Handle relative URLs
    if isinstance(to, str) and to.startswith(("./", "../")):
        return to

    # Next try a reverse URL resolution.
    try:
        return reverse(to, args=args, kwargs=kwargs)
    except NoReverseMatch:
        # If this is a callable, re-raise.
        if callable(to):
            raise
        # If this doesn't "feel" like a URL, re-raise.
        if "/" not in to and "." not in to:
            raise

    # Finally, fall back and assume it's a URL
    return to


def update_session_auth_hash(request, user):
    """
    Updating a user's password logs out all sessions for the user.

    Take the current request and the updated user object from which the new
    session hash will be derived and update the session hash appropriately to
    prevent a password change from logging out the session from which the
    password was changed.
    """
    request.session.cycle_key()
    if hasattr(user, "get_session_auth_hash") and request.user == user:
        request.session[USER_HASH_SESSION_KEY] = user.get_session_auth_hash()


# Class-based password reset views
# - PasswordResetView sends the mail
# - PasswordResetDoneView shows a success message for the above
# - PasswordResetConfirmView checks the link the user clicked and
#   prompts for a new password
# - PasswordResetCompleteView shows a success message for the above


class PasswordContextMixin:
    extra_context = None

    def get_template_context(self):
        context = super().get_template_context()
        context.update(
            {"title": self.title, "subtitle": None, **(self.extra_context or {})}
        )
        return context


class PasswordResetView(PasswordContextMixin, FormView):
    email_template_name = "auth/password_reset_email.html"
    extra_email_context = None
    form_class = PasswordResetForm
    from_email = None
    html_email_template_name = None
    subject_template_name = "auth/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")
    template_name = "auth/password_reset_form.html"
    title = "Password reset"
    token_generator = default_token_generator

    def form_valid(self, form):
        opts = {
            "use_https": self.request.is_secure(),
            "token_generator": self.token_generator,
            "from_email": self.from_email,
            "email_template_name": self.email_template_name,
            "subject_template_name": self.subject_template_name,
            "html_email_template_name": self.html_email_template_name,
            "extra_email_context": self.extra_email_context,
        }
        form.save(**opts)
        return super().form_valid(form)


INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"


class PasswordResetDoneView(PasswordContextMixin, TemplateView):
    template_name = "auth/password_reset_done.html"
    title = "Password reset sent"


class PasswordResetConfirmView(PasswordContextMixin, FormView):
    form_class = SetPasswordForm
    post_reset_login = False
    post_reset_login_backend = None
    reset_url_token = "set-password"
    success_url = reverse_lazy("password_reset_complete")
    template_name = "auth/password_reset_confirm.html"
    title = "Enter new password"
    token_generator = default_token_generator

    def get_response(self):
        if "uidb64" not in self.url_kwargs or "token" not in self.url_kwargs:
            raise ImproperlyConfigured(
                "The URL path must contain 'uidb64' and 'token' parameters."
            )

        self.validlink = False
        self.user = self.get_user(self.url_kwargs["uidb64"])

        if self.user is not None:
            token = self.url_kwargs["token"]
            if token == self.reset_url_token:
                session_token = self.request.session.get(INTERNAL_RESET_SESSION_TOKEN)
                if self.token_generator.check_token(self.user, session_token):
                    # If the token is valid, display the password reset form.
                    self.validlink = True
                    response = super().get_response()
                    add_never_cache_headers(response)
                    return response
            else:
                if self.token_generator.check_token(self.user, token):
                    # Store the token in the session and redirect to the
                    # password reset form at a URL without the token. That
                    # avoids the possibility of leaking the token in the
                    # HTTP Referer header.
                    self.request.session[INTERNAL_RESET_SESSION_TOKEN] = token
                    redirect_url = self.request.path.replace(
                        token, self.reset_url_token
                    )
                    response = ResponseRedirect(redirect_url)
                    add_never_cache_headers(response)
                    return response

        # Display the "Password reset unsuccessful" page.
        response = self.render_to_response(self.get_template_context())
        add_never_cache_headers(response)
        return response

    def get_user(self, uidb64):
        UserModel = get_user_model()
        try:
            # urlsafe_base64_decode() decodes to bytestring
            uid = urlsafe_base64_decode(uidb64).decode()
            user = UserModel._default_manager.get(pk=uid)
        except (
            TypeError,
            ValueError,
            OverflowError,
            UserModel.DoesNotExist,
            ValidationError,
        ):
            user = None
        return user

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.user
        return kwargs

    def form_valid(self, form):
        user = form.save()
        del self.request.session[INTERNAL_RESET_SESSION_TOKEN]
        if self.post_reset_login:
            auth_login(self.request, user, self.post_reset_login_backend)
        return super().form_valid(form)

    def get_template_context(self):
        context = super().get_template_context()
        if self.validlink:
            context["validlink"] = True
        else:
            context.update(
                {
                    "form": None,
                    "title": "Password reset unsuccessful",
                    "validlink": False,
                }
            )
        return context


class PasswordResetCompleteView(PasswordContextMixin, TemplateView):
    template_name = "auth/password_reset_complete.html"
    title = "Password reset complete"

    def get_template_context(self):
        context = super().get_template_context()
        context["login_url"] = resolve_url(settings.LOGIN_URL)
        return context


class PasswordChangeView(PasswordContextMixin, AuthViewMixin, FormView):
    form_class = PasswordChangeForm
    success_url = reverse_lazy("password_change_done")
    template_name = "auth/password_change_form.html"
    title = "Password change"
    login_required = True

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.save()
        # Updating the password logs out all other sessions for the user
        # except the current one.
        update_session_auth_hash(self.request, form.user)
        return super().form_valid(form)


class PasswordChangeDoneView(PasswordContextMixin, AuthViewMixin, TemplateView):
    template_name = "auth/password_change_done.html"
    title = "Password change successful"
    login_required = True
