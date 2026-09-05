-- BRAINDOCS Supabase Database Schema
-- Run this SQL in your Supabase SQL Editor (https://app.supabase.com -> Project -> SQL Editor)

-- 1. Create Profiles Table (Linked with Supabase Auth users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    username TEXT UNIQUE,
    password TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Ensure password column exists if updating existing profiles table
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS password TEXT;

-- Index for fast username lookups
CREATE INDEX IF NOT EXISTS idx_profiles_username ON public.profiles(username);

-- 2. Create Documents Table
CREATE TABLE IF NOT EXISTS public.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    chunk_count INT DEFAULT 0,
    visibility TEXT DEFAULT 'public',
    namespace TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Index for fast user/username document queries
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON public.documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_username ON public.documents(username);

-- 3. Create Chat Logs Table (Stores visitor interactions with chatbots)
CREATE TABLE IF NOT EXISTS public.chat_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_username TEXT NOT NULL,
    visitor_email TEXT NOT NULL,
    session_id TEXT,
    user_message TEXT NOT NULL,
    bot_response TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Index for fast chatbot log filtering by bot owner, visitor email and session_id
CREATE INDEX IF NOT EXISTS idx_chat_logs_bot_username ON public.chat_logs(bot_username);
CREATE INDEX IF NOT EXISTS idx_chat_logs_visitor_email ON public.chat_logs(visitor_email);
CREATE INDEX IF NOT EXISTS idx_chat_logs_session_id ON public.chat_logs(session_id);

-- 4. Automatically create profile entry when new auth user signs up
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, email)
  VALUES (new.id, new.email)
  ON CONFLICT (id) DO NOTHING;
  RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to execute handle_new_user on user creation
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();

-- 5. Row Level Security (RLS) Configuration
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_logs ENABLE ROW LEVEL SECURITY;

-- Profiles Policies
DROP POLICY IF EXISTS "Public profiles are readable by everyone" ON public.profiles;
DROP POLICY IF EXISTS "Users can update their own profile" ON public.profiles;
DROP POLICY IF EXISTS "Allow profile select" ON public.profiles;
DROP POLICY IF EXISTS "Allow profile insert" ON public.profiles;
DROP POLICY IF EXISTS "Allow profile update" ON public.profiles;

CREATE POLICY "Allow profile select" ON public.profiles FOR SELECT USING (true);
CREATE POLICY "Allow profile insert" ON public.profiles FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow profile update" ON public.profiles FOR UPDATE USING (true);

-- Documents Policies
DROP POLICY IF EXISTS "Documents readable by owner or public chatbot lookup" ON public.documents;
DROP POLICY IF EXISTS "Users can insert their own documents" ON public.documents;
DROP POLICY IF EXISTS "Users can delete their own documents" ON public.documents;
DROP POLICY IF EXISTS "Allow documents select" ON public.documents;
DROP POLICY IF EXISTS "Allow documents insert" ON public.documents;
DROP POLICY IF EXISTS "Allow documents delete" ON public.documents;

CREATE POLICY "Allow documents select" ON public.documents FOR SELECT USING (true);
CREATE POLICY "Allow documents insert" ON public.documents FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow documents delete" ON public.documents FOR DELETE USING (true);

-- Chat Logs Policies
DROP POLICY IF EXISTS "Chat logs insertable by anyone (visitors)" ON public.chat_logs;
DROP POLICY IF EXISTS "Chat logs readable by bot owner" ON public.chat_logs;
DROP POLICY IF EXISTS "Allow chat_logs select" ON public.chat_logs;
DROP POLICY IF EXISTS "Allow chat_logs insert" ON public.chat_logs;

CREATE POLICY "Allow chat_logs select" ON public.chat_logs FOR SELECT USING (true);
CREATE POLICY "Allow chat_logs insert" ON public.chat_logs FOR INSERT WITH CHECK (true);

-- 6. Storage Bucket RLS Policies for 'braindocs' Bucket
-- Execute these queries to allow reading, uploading, updating, and deleting files in your Supabase storage bucket
DROP POLICY IF EXISTS "Allow storage select on braindocs" ON storage.objects;
DROP POLICY IF EXISTS "Allow storage insert on braindocs" ON storage.objects;
DROP POLICY IF EXISTS "Allow storage update on braindocs" ON storage.objects;
DROP POLICY IF EXISTS "Allow storage delete on braindocs" ON storage.objects;

CREATE POLICY "Allow storage select on braindocs" ON storage.objects FOR SELECT USING (bucket_id = 'braindocs');
CREATE POLICY "Allow storage insert on braindocs" ON storage.objects FOR INSERT WITH CHECK (bucket_id = 'braindocs');
CREATE POLICY "Allow storage update on braindocs" ON storage.objects FOR UPDATE USING (bucket_id = 'braindocs');
CREATE POLICY "Allow storage delete on braindocs" ON storage.objects FOR DELETE USING (bucket_id = 'braindocs');
