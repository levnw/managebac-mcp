"""Password sign-in and session verification only. No academic retrieval or tools.

The profile route and account controls were observed in a prior authenticated
school capture. This verifier must still be confirmed on a fresh live login.
"""
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .transport import Transport, FlowError, school_origin, soup_of


class Authenticator(Transport):
    async def authenticate(self, client, origin, email, password):
        origin = school_origin(origin)
        client.cookies.clear()  # Never validate a previous user's session.
        page = soup_of(await client.get(origin + "/login"))
        form = page.select_one('form[action="/sessions"]')
        csrf = page.select_one('meta[name="csrf-token"]')
        if not form or not csrf:
            raise FlowError("unsupported_signin", "This school's sign-in form needs review, possibly for SSO or two-factor authentication.")
        response = await client.post(origin + "/sessions", data={"login": email,
            "password": password, "authenticity_token": csrf.get("content", ""), "commit": "Sign in"})
        self.check_rejection(response)
        # Do not follow the form's potentially academic landing page. Use the
        # observed account profile solely to establish an authenticated session.
        return await self.verify_session(client, origin)

    @staticmethod
    def check_rejection(response):
        page = BeautifulSoup(response.text, "html.parser")
        text = page.get_text(" ", strip=True).lower()
        if "temporarily locked" in text or "consecutive failed" in text:
            raise FlowError("account_locked", "ManageBac reports an account lock. Stop retrying and use your school's recovery process.")
        if response.status_code == 429:
            raise FlowError("rate_limited", "ManageBac is limiting sign-ins. Wait before trying again.")
        if response.status_code >= 400 or page.select_one('input[type="password"]'):
            raise FlowError("signin_not_completed", "ManageBac did not complete sign-in. No automatic retry was made.")

    async def verify_session(self, client, origin, *, existing_session=False):
        destination = origin + "/student/profile"
        for _ in range(5):
            # Only account routes may be followed; never classes/tasks/dashboard.
            if school_origin(destination) != origin or urlsplit(destination).path.rstrip('/') != '/student/profile':
                raise FlowError("session_unverified", "ManageBac redirected away from the account page. Sign-in cannot yet be verified; this does not prove the password is wrong.")
            response = await client.get(destination)
            if existing_session:
                # Positive authentication evidence only. Timeouts, 403/429/5xx,
                # unknown markup and unrelated redirects do not prove expiry.
                login_redirect = False
                if response.is_redirect and response.headers.get('location'):
                    target = urlsplit(urljoin(destination, response.headers['location']))
                    login_redirect = (target.scheme + '://' + target.netloc == origin
                                      and target.path.rstrip('/') in ('/login', '/sessions'))
                page = BeautifulSoup(response.text, 'html.parser') if response.status_code == 200 else None
                login_form = page is not None and page.select_one('form[action="/sessions"] input[type="password"]') is not None
                if response.status_code == 401 or login_redirect or login_form:
                    raise FlowError('session_expired', 'The account profile requires sign-in. Reconnect your account.')
            self.check_rejection(response)
            if response.is_redirect:
                location = response.headers.get('location')
                if not location:
                    raise FlowError("session_unverified", "ManageBac returned an incomplete sign-in redirect.")
                destination = urljoin(destination, location)
                continue
            page = soup_of(response)
            profile = page.select_one('a.profile-link[href="/student/profile"][aria-label]')
            logout = page.select_one('a.logout[href="/logout"]')
            if not profile or not profile.get('aria-label', '').strip() or not logout:
                raise FlowError("session_unverified", "The expected signed-in account controls were not found. Authentication needs review.")
            # Do not extract the profile body, grades, age, or other profile data.
            return {"authenticated": True, "verification": "profile_account_controls"}
        raise FlowError("redirect_loop", "ManageBac redirected repeatedly. Sign-in verification was stopped.")
