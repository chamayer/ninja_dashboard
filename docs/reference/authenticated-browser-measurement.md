# Authenticated browser measurement

Use this method only for approved, read-only performance verification of the
Operations UI. It measures the browser navigation path in addition to the
server-side request timing; neither replaces the other.

## Preconditions

- Use an existing local Chromium-family browser in headless mode. Microsoft
  Edge is available on the development workstation at the time of writing.
- Reach the deployed Operations container through an SSH local port forward to
  its loopback-only HTTP port. This avoids exposing the service or changing its
  deployment configuration.
- Obtain the existing `admin` password from the Docker host's `.env` file only
  in the process that starts the measurement. Do not print it, write it to a
  script, store it in a browser profile, or add it to this repository.

## Method

1. Start a temporary SSH local forward to the Operations HTTP port.
2. Start a temporary, headless Edge profile with the DevTools remote-debugging
   protocol bound to localhost.
3. Use a short, in-memory DevTools Protocol client to load Django's admin
   login form, submit the existing `admin` credentials, and navigate the
   target GET routes. Do not invoke action endpoints or submit any other form.
4. For each route, record the Navigation Timing values for `responseStart`,
   `domContentLoadedEventEnd`, and `duration`, plus the transfer size. Repeat
   warm runs when comparing changes.
5. End the SSH session and browser, then remove the temporary browser profile.

## Interpretation and boundaries

- `responseStart` is the clearest browser-observed proxy for server response
  latency. `duration` also includes browser parsing and subresource work.
- The SSH hop is local to the measurement workstation, so this is not an
  Internet end-user latency test. It is an authenticated rendering and
  navigation check against the deployed stack.
- Keep raw route timings in the active `BLUEPRINT.md` and plan evidence, not
  in this reference. They expire as code and production data change.
- The method is read-only: use only authenticated GET navigation and the login
  POST required to establish a session. It does not authorize deployment,
  migrations, production data changes, or manual operational actions.
