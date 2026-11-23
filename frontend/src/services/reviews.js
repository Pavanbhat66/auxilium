import { collection, getDocs, serverTimestamp, setDoc, doc } from "firebase/firestore";
import { auth, db, firebaseConfigured } from "../lib/firebase";

function reviewCollection() {
  const userId = auth?.currentUser?.uid;
  return userId && db ? collection(db, "users", userId, "evidenceReviews") : null;
}

export async function loadReviewDecisions() {
  if (!firebaseConfigured || !db || !auth?.currentUser) return {};
  const snapshot = await getDocs(reviewCollection());
  return Object.fromEntries(snapshot.docs.map((item) => {
    const data = item.data();
    return [item.id, { decision: data.status || "pending", notes: data.reviewerNotes || "" }];
  }));
}

export async function saveReviewDecision(evidenceId, status, reviewerNotes = "") {
  const reviews = reviewCollection();
  if (!firebaseConfigured || !reviews || !auth.currentUser) return false;
  await setDoc(doc(reviews, evidenceId), {
    evidenceId,
    status,
    reviewerId: auth.currentUser.uid,
    reviewerNotes,
    updatedAt: serverTimestamp(),
  }, { merge: true });
  return true;
}
