import { GoogleAuthProvider, browserLocalPersistence, onAuthStateChanged, setPersistence, signInWithPopup, signOut, updateProfile } from "firebase/auth";
import { doc, getDoc, serverTimestamp, setDoc } from "firebase/firestore";
import { auth, db, firebaseConfigured } from "../lib/firebase";

function requireAuth() {
  if (!firebaseConfigured || !auth) {
    throw new Error("Firebase Authentication is not configured. Check frontend/.env.local.");
  }
}

export const authPersistenceReady = auth
  ? setPersistence(auth, browserLocalPersistence)
  : Promise.resolve();

export function observeSession(callback, onError) {
  if (!firebaseConfigured || !auth) return () => {};
  return onAuthStateChanged(auth, callback, onError);
}

export async function signInWithGoogle() {
  requireAuth();
  await authPersistenceReady;
  await signInWithPopup(auth, new GoogleAuthProvider());
}

export function createAppUser(firebaseUser, profile = {}) {
  return {
    id: firebaseUser.uid,
    name: profile.name || firebaseUser.displayName || "Google user",
    email: profile.email || firebaseUser.email || "",
    accessibilityProfile: profile.accessibilityProfile || "general",
  };
}

export async function loadUserProfile(firebaseUser) {
  requireAuth();
  if (!db) return null;
  const snapshot = await getDoc(doc(db, "users", firebaseUser.uid));
  if (!snapshot.exists()) {
    const profile = createAppUser(firebaseUser);
    await setDoc(doc(db, "users", firebaseUser.uid), {
      name: profile.name,
      email: profile.email,
      accessibilityProfile: profile.accessibilityProfile,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    }, { merge: true });
    return profile;
  }
  return createAppUser(firebaseUser, snapshot.data());
}

export async function saveUserProfile(user) {
  requireAuth();
  if (auth.currentUser && auth.currentUser.displayName !== user.name) {
    await updateProfile(auth.currentUser, { displayName: user.name });
  }
  if (!db) throw new Error("Cloud profile storage is not configured.");
  await setDoc(doc(db, "users", user.id), {
    name: user.name,
    email: user.email,
    accessibilityProfile: user.accessibilityProfile,
    updatedAt: serverTimestamp(),
  }, { merge: true });
  if (auth.currentUser && auth.currentUser.displayName !== user.name) {
    await updateProfile(auth.currentUser, { displayName: user.name });
  }
}

export async function logOut() {
  requireAuth();
  await signOut(auth);
}
