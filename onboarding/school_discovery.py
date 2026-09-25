"""Email-to-school discovery and login-page branding only."""
import re
from urllib.parse import urljoin, urlsplit
from .transport import Transport, FlowError, email_value, school_origin, soup_of

class SchoolDiscovery(Transport):
    async def discover(self, email):
        email = email_value(email)
        async with self.client() as c:
            root = "https://signin.managebac.com"
            page = soup_of(await c.get(root + "/"))
            token = page.select_one('meta[name="csrf-token"]')
            if not token:
                raise FlowError("discovery_changed", "The school finder has changed. Discovery needs review.")
            r = await c.post(root + "/signups/find-school", data={
                "find_school[email]": email, "find_school[subdomain]": "",
                "find_school[region]": "managebac.com", "commit": "Continue",
            }, headers={"X-CSRF-Token": token.get("content", ""),
                        "X-Requested-With": "XMLHttpRequest", "Accept": "*/*"})
            if r.status_code == 429:
                raise FlowError("rate_limited", "School discovery is busy. Wait before trying again.")
            destination = r.headers.get("location")
            if not destination:
                match = re.search(r'Turbolinks\.visit\("(https://[^" ]+)"', r.text)
                destination = match.group(1) if match else None
            if not destination:
                raise FlowError("school_not_found", "No school was resolved. Check the email used in ManageBac.")
            origin = school_origin(destination)
            page = soup_of(await c.get(origin + "/login"))
            title = page.select_one("h3")
            # School logo selection is scoped to the login header; no default school.
            image = page.select_one(".session-logo img, .school-logo img, #session_form img")
            logo = urljoin(origin, image.get("src", "")) if image else None
            if logo and urlsplit(logo).scheme != "https":
                logo = None
            return {"origin": origin, "name": title.get_text(" ", strip=True) if title else urlsplit(origin).hostname,
                    "logo": logo}
