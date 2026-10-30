import { useEffect, useMemo, useState } from "react";
import MapView from "./components/MapView";
import { calculateRouteScore } from "./utils/accessibility";
import { firebaseConfigured } from "./lib/firebase";
import { createAppUser, loadUserProfile, logOut, observeSession, saveUserProfile, signInWithGoogle } from "./services/auth";

function profileLabel(profile) {
  if (profile === "wheelchair") return "Wheelchair";
  if (profile === "walking_difficulty") return "Walking support";
  return "General";
}

function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [routeDetails, setRouteDetails] = useState(null);
  const [mobileControlsOpen, setMobileControlsOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState("accessibility");

  useEffect(() => {
    if (!firebaseConfigured) {
      setAuthLoading(false);
      return undefined;
    }
    return observeSession(async (firebaseUser) => {
      if (!firebaseUser) {
        setUser(null);
        setAuthLoading(false);
        return;
      }
      setUser(createAppUser(firebaseUser));
      setAuthLoading(false);
      try {
        const profile = await loadUserProfile(firebaseUser);
        if (profile) setUser((currentUser) => currentUser?.id === profile.id ? profile : currentUser);
      } catch {
        setAuthError("Signed in successfully. Cloud profile sync is unavailable right now.");
      }
    }, (error) => {
      setAuthError(error.message);
      setAuthLoading(false);
    });
  }, []);
  const routeSegments = useMemo(() => [
    { stairs: false, slope: "low", ramp: true, surface: "good", obstacles: false },
    { stairs: false, slope: "low", ramp: true, surface: "good", obstacles: false },
    { stairs: false, slope: "low", ramp: true, surface: "good", obstacles: false },
  ], []);
  const score = calculateRouteScore(user?.accessibilityProfile || "general", routeSegments);

  async function saveUser(nextUser) {
    try {
      await saveUserProfile(nextUser);
      setUser(nextUser);
    } catch (error) {
      setAuthError(error.message);
    }
  }

  async function handleGoogleSignIn() {
    setAuthError("");
    try {
      await signInWithGoogle();
    } catch (error) {
      if (error.code === "auth/unauthorized-domain") {
        setAuthError(`This app domain is not authorized in Firebase: ${window.location.hostname}.`);
      } else if (error.code === "auth/operation-not-allowed") {
        setAuthError("Google sign-in is not enabled in Firebase Authentication.");
      } else if (error.code === "auth/api-key-not-valid") {
        setAuthError("The Firebase web API key is invalid. Copy the current web app config into frontend/.env.local.");
      } else if (error.code === "auth/popup-blocked") {
        setAuthError("Your browser blocked the Google sign-in window. Allow popups for localhost and try again.");
      } else if (error.code === "auth/popup-closed-by-user") {
        setAuthError("Google sign-in was cancelled.");
      } else if (error.code === "auth/network-request-failed") {
        setAuthError("Unable to reach Firebase. Check your internet connection and try again.");
      } else {
        setAuthError(error.message);
      }
    }
  }

  async function handleSignOut() {
    await logOut();
    setProfileOpen(false);
    setUser(null);
  }

  if (authLoading) return <main className="auth-page"><section className="auth-panel"><p className="eyebrow">AUXILIUM</p><h1>Checking your session…</h1></section></main>;

  if (!user) {
    return <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <p className="eyebrow">AUXILIUM</p>
        <h1 id="auth-title">Move through your city with more clarity.</h1>
        <p className="auth-intro">Plan routes with your mobility needs in view.</p>
        {authError && <p className="form-error" role="alert">{authError}</p>}
        {!firebaseConfigured && <p className="form-error" role="alert">Firebase is not configured yet. Add the project values to <code>frontend/.env.local</code>.</p>}
        <button className="google-button" type="button" onClick={handleGoogleSignIn} disabled={!firebaseConfigured}>Continue with Google</button>
        <p className="local-note">Your account and mobility profile are stored securely through Firebase.</p>
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
      <p className="panel-copy">Compare road-network route options. Accessibility conditions are not yet used to filter them.</p>
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
          <p className="sheet-copy">Routes are not yet filtered by accessibility conditions.</p>
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
        <button className="secondary-button" type="button" onClick={handleSignOut}>Log out</button>
      </section>
    </div>}
  </main>;
}

export default App;
