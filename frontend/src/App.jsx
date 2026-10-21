import { useMemo, useState } from "react";
import MapView from "./components/MapView";
import { calculateRouteScore } from "./utils/accessibility";

const USERS_KEY = "auxilium-users";
const SESSION_KEY = "auxilium-session";

function readStoredValue(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) || fallback;
  } catch {
    return fallback;
  }
}

function profileLabel(profile) {
  if (profile === "wheelchair") return "Wheelchair";
  if (profile === "walking_difficulty") return "Walking support";
  return "General";
}

function App() {
  const [user, setUser] = useState(() => readStoredValue(SESSION_KEY, null));
  const [authMode, setAuthMode] = useState("login");
  const [authError, setAuthError] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [routeDetails, setRouteDetails] = useState(null);
  const [mobileControlsOpen, setMobileControlsOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState("accessibility");
  const routeSegments = useMemo(() => [
    { stairs: false, slope: "low", ramp: true, surface: "good", obstacles: false },
    { stairs: false, slope: "low", ramp: true, surface: "good", obstacles: false },
    { stairs: false, slope: "low", ramp: true, surface: "good", obstacles: false },
  ], []);
  const score = calculateRouteScore(user?.accessibilityProfile || "general", routeSegments);

  function saveUser(nextUser) {
    const users = readStoredValue(USERS_KEY, []).map((storedUser) =>
      storedUser.id === nextUser.id ? nextUser : storedUser,
    );
    localStorage.setItem(USERS_KEY, JSON.stringify(users));
    localStorage.setItem(SESSION_KEY, JSON.stringify(nextUser));
    setUser(nextUser);
  }

  function handleAuth(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = form.get("email").trim().toLowerCase();
    const password = form.get("password");
    const name = form.get("name")?.trim();
    const users = readStoredValue(USERS_KEY, []);

    if (authMode === "signup") {
      if (!name || !email || !password) return setAuthError("Complete each field to create your account.");
      if (users.some((storedUser) => storedUser.email === email)) return setAuthError("An account already exists for this email.");
      const nextUser = { id: crypto.randomUUID(), name, email, password, accessibilityProfile: "general" };
      localStorage.setItem(USERS_KEY, JSON.stringify([...users, nextUser]));
      localStorage.setItem(SESSION_KEY, JSON.stringify(nextUser));
      setUser(nextUser);
      return;
    }

    const matchingUser = users.find((storedUser) => storedUser.email === email && storedUser.password === password);
    if (!matchingUser) return setAuthError("Email or password is incorrect.");
    localStorage.setItem(SESSION_KEY, JSON.stringify(matchingUser));
    setUser(matchingUser);
  }

  function switchAuthMode(mode) {
    setAuthMode(mode);
    setAuthError("");
  }

  function signOut() {
    localStorage.removeItem(SESSION_KEY);
    setProfileOpen(false);
    setUser(null);
  }

  if (!user) {
    return <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <p className="eyebrow">AUXILIUM</p>
        <h1 id="auth-title">Move through your city with more clarity.</h1>
        <p className="auth-intro">Plan routes with your mobility needs in view.</p>
        <div className="auth-tabs" role="tablist" aria-label="Account actions">
          <button className={authMode === "login" ? "active" : ""} onClick={() => switchAuthMode("login")} type="button">Log in</button>
          <button className={authMode === "signup" ? "active" : ""} onClick={() => switchAuthMode("signup")} type="button">Sign up</button>
        </div>
        <form className="auth-form" onSubmit={handleAuth}>
          {authMode === "signup" && <label>Full name<input name="name" autoComplete="name" placeholder="Your name" /></label>}
          <label>Email<input name="email" type="email" autoComplete="email" placeholder="you@example.com" required /></label>
          <label>Password<input name="password" type="password" autoComplete={authMode === "signup" ? "new-password" : "current-password"} placeholder="Your password" required /></label>
          {authError && <p className="form-error" role="alert">{authError}</p>}
          <button className="primary-button" type="submit">{authMode === "signup" ? "Create account" : "Continue"}</button>
        </form>
        <p className="local-note">This prototype stores account details only in this browser.</p>
      </section>
      <aside className="auth-aside"><p>Accessible journeys begin with a route that considers you.</p></aside>
    </main>;
  }

  return <main className="map-page">
    <MapView profile={user.accessibilityProfile} onRouteChange={setRouteDetails} />
    <header className="top-bar">
      <div className="brand"><span>AUXILIUM</span><small>Accessible routing</small></div>
      <div className="map-search" aria-label="Route instructions">Select a start point, then select a destination on the map.</div>
      <button className="account-button" type="button" onClick={() => setProfileOpen(true)}>{user.name}</button>
    </header>
    <section className="route-panel" aria-label="Route settings">
      <p className="eyebrow">Route preferences</p><h1>Plan your way</h1>
      <p className="panel-copy">Your selected profile adjusts how this prototype requests a route.</p>
      <div className="preference-list" role="group" aria-label="Accessibility profile">
        {[["general", "General"], ["wheelchair", "Wheelchair"], ["walking_difficulty", "Walking support"]].map(([value, label]) =>
          <button key={value} className={user.accessibilityProfile === value ? "preference active" : "preference"} type="button" onClick={() => saveUser({ ...user, accessibilityProfile: value })}>{label}</button>,
        )}
      </div>
      <div className="route-summary"><span>Accessibility score</span><strong>{score}<small>/100</small></strong>{routeDetails ? <p>{(routeDetails.distance / 1000).toFixed(2)} km · {Math.round(routeDetails.duration / 60)} min</p> : <p>Choose two points to see a route.</p>}</div>
    </section>
    <div className="map-hint">Click once for your start. Click again for your destination.</div>
    <div className="mobile-controls">
      {mobileControlsOpen && <section className="mobile-control-sheet" aria-label="Control center">
        <div className="sheet-handle" />
        <div className="mobile-tabs" role="tablist" aria-label="Control center sections">
          <button className={mobileTab === "accessibility" ? "active" : ""} type="button" onClick={() => setMobileTab("accessibility")}>Accessibility</button>
          <button className={mobileTab === "route" ? "active" : ""} type="button" onClick={() => setMobileTab("route")}>Route</button>
        </div>
        {mobileTab === "accessibility" ? <div className="mobile-tab-content">
          <p className="sheet-label">Mobility profile</p>
          <div className="mobile-preference-list" role="group" aria-label="Accessibility profile">
            {[["general", "General"], ["wheelchair", "Wheelchair"], ["walking_difficulty", "Walking support"]].map(([value, label]) =>
              <button key={value} className={user.accessibilityProfile === value ? "preference active" : "preference"} type="button" onClick={() => saveUser({ ...user, accessibilityProfile: value })}>{label}</button>,
            )}
          </div>
          <p className="sheet-copy">Your profile adjusts how the prototype requests the route.</p>
        </div> : <div className="mobile-tab-content route-tab-content">
          <span>Accessibility score</span><strong>{score}<small>/100</small></strong>
          {routeDetails ? <p>{(routeDetails.distance / 1000).toFixed(2)} km · {Math.round(routeDetails.duration / 60)} min</p> : <p>Choose two points on the map to see route details.</p>}
        </div>}
      </section>}
      <button className="mobile-control-toggle" type="button" onClick={() => setMobileControlsOpen((open) => !open)} aria-expanded={mobileControlsOpen}>{mobileControlsOpen ? "Close controls" : "Control center"}</button>
    </div>
    {profileOpen && <div className="dialog-backdrop" role="presentation" onMouseDown={() => setProfileOpen(false)}>
      <section className="profile-dialog" role="dialog" aria-modal="true" aria-labelledby="profile-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="dialog-heading"><div><p className="eyebrow">Your account</p><h2 id="profile-title">Profile</h2></div><button className="text-button" type="button" onClick={() => setProfileOpen(false)}>Close</button></div>
        <label className="profile-field">Name<input value={user.name} onChange={(event) => setUser({ ...user, name: event.target.value })} /></label>
        <label className="profile-field">Email<input value={user.email} readOnly /></label>
        <div className="profile-current"><span>Current mobility profile</span><strong>{profileLabel(user.accessibilityProfile)}</strong></div>
        <button className="primary-button" type="button" onClick={() => { saveUser(user); setProfileOpen(false); }}>Save profile</button>
        <button className="secondary-button" type="button" onClick={signOut}>Log out</button>
      </section>
    </div>}
  </main>;
}

export default App;
