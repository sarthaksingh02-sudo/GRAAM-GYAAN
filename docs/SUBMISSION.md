# Project Tagline
GRAAM-GYAAN is a multilingual, voice-first AI assistant that helps rural households understand government schemes, find official regional updates, and navigate documents in their own language.

# Describe Your Solution
GRAAM-GYAAN brings welfare information into a conversational interface. Users can speak or type questions, set their village, panchayat, block, district and state, and maintain a household profile to receive relevant guidance. Sarvam AI powers conversation, speech recognition, spoken answers and document extraction. The application combines source-linked scheme records, preliminary eligibility checks, document review and refreshable official district listings. Users can switch locations, inspect source links and check times, and access previously cached public guides when connectivity is limited. Sensitive document identifiers are masked, and proposed profile changes require confirmation. The MVP makes discovery and next steps easier while leaving final eligibility and benefit approval to the responsible authority.

# What Problem Are You Solving?
Rural households often need to search multiple government websites, understand formal documents and visit offices to learn which schemes or local initiatives may apply to them. Language barriers, limited digital literacy and unreliable connectivity make this process harder. GRAAM-GYAAN offers a single place to ask questions in familiar language, understand required documents and reach official sources without treating unverified information as a guaranteed benefit.

# What Makes Your Solution Different?
Our approach combines conversation with household and location context. Voice input and spoken answers improve accessibility; document extraction turns paperwork into reviewable fields; source links and freshness labels help users verify guidance. Switching locations changes the regional feed instead of showing a fixed demo village. The system distinguishes district notices from confirmed village works and labels saved-source fallbacks when the AI service fails. Cached public guides remain useful offline, while live AI and source refreshes require connectivity.

# What challenges did your team face while building the project?
The main challenges were connecting the frontend to a reliable AI backend, handling speech formats and provider failures, maintaining follow-up context, and extracting useful information from inconsistent government websites. Regional coverage and publication dates are not uniform, so we had to distinguish source-check times from actual publication dates and avoid presenting district notices as confirmed village projects. We also implemented document masking, explicit confirmation for profile updates, browser-specific household isolation for public hosting, and clear offline and temporary-storage behaviour.

# GitHub Repository Link
https://github.com/sarthaksingh02-sudo/GRAAM-GYAAN

# Live Project / Deployment Link
Pending verified deployment. Replace this line with the tested Vercel URL; localhost is not a public deployment.

# Submission accuracy
The MVP does not guarantee exhaustive or always-current government data. District discovery depends on accessible official websites. Local saved scheme records are a limited catalogue, and eligibility is preliminary. Free Render hosting uses temporary storage that may reset. Account login and recovery are not implemented.
