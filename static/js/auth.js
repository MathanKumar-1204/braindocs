// BRAINDOCS Frontend Authentication Module via Supabase OAuth

let supabaseClient = null;

function initSupabase() {
    if (window.SUPABASE_URL && window.SUPABASE_ANON_KEY && window.SUPABASE_URL.includes("https://")) {
        try {
            supabaseClient = supabase.createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);
            console.log("Supabase Client initialized on frontend.");
        } catch (err) {
            console.error("Supabase client init error:", err);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initSupabase();

    // Check if handling OAuth redirect callback
    if (window.location.pathname === '/auth/callback' || window.location.hash.includes('access_token')) {
        handleAuthCallback();
    }
});

async function handleGoogleSignIn() {
    if (!supabaseClient) {
        // Fallback for development demo if Supabase keys not set
        const mockEmail = prompt("Supabase credentials not configured in .env yet.\n\nEnter a demo email address to log in:", "user@example.com");
        if (mockEmail) {
            loginWithSession({
                id: "demo-user-id-123",
                email: mockEmail
            });
        }
        return;
    }

    try {
        const { data, error } = await supabaseClient.auth.signInWithOAuth({
            provider: 'google',
            options: {
                redirectTo: `${window.location.origin}/auth/callback`
            }
        });
        if (error) {
            alert('Google Auth Error: ' + error.message);
        }
    } catch (err) {
        console.error('OAuth sign in error:', err);
    }
}

async function handleAuthCallback() {
    if (!supabaseClient) return;

    const { data: { session }, error } = await supabaseClient.auth.getSession();
    if (error || !session) {
        console.error('Failed to retrieve session from callback:', error);
        window.location.href = '/';
        return;
    }

    // Send session user info to Flask backend
    loginWithSession({
        id: session.user.id,
        email: session.user.email
    });
}

async function loginWithSession(userObj) {
    try {
        const res = await fetch('/api/auth/session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(userObj)
        });
        const data = await res.json();
        if (data.redirect) {
            window.location.href = data.redirect;
        } else {
            window.location.href = '/dashboard';
        }
    } catch (err) {
        console.error('Session sync error:', err);
    }
}

async function handleSignOut() {
    if (supabaseClient) {
        await supabaseClient.auth.signOut();
    }
    window.location.href = '/auth/logout';
}
