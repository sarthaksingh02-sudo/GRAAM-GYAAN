# Tool Definitions for GRAAM-GYAAN Voice Assistant

## 1. `get_profile`
- **Description**: Retrieves the household profile, village/district location, registered family members with their calculated age in years, and checklist of missing documents.
- **Parameters**: None

## 2. `update_profile`
- **Description**: Proposes or confirms an update to the user profile or family member details. Always generates a spoken confirmation request with what was understood before committing.
- **Parameters**:
  - `field` (string): Field to update (e.g., `village`, `district`, `occupation`, `caste_category`, `land_acres`)
  - `value` (any): New proposed value
  - `member_name` (optional string): Name or relation of family member if updating a member

## 3. `explain_document`
- **Description**: Explains or summarizes an uploaded or referenced document, answering citizen questions regarding action steps, deadlines, and requirements.
- **Parameters**:
  - `doc_type` (optional string): Document type or name
  - `question` (optional string): Specific citizen question about the document

## 4. `find_schemes`
- **Description**: Searches verified government schemes from `/data/real/schemes` matching the household criteria (state, caste, occupation, land ownership, age, gender).
- **Parameters**:
  - `query` (optional string): Keyword or topic (e.g. "farmer", "daughter", "housing", "pension", "health")
  - `member_name` (optional string): Target family member to match

## 5. `get_regional_projects`
- **Description**: Retrieves ongoing and upcoming government development projects (Centre & State) in the citizen's district and state from `/data/real/projects`.
- **Parameters**:
  - `district` (optional string): District name
  - `state` (optional string): State name

## 6. `get_needs_guide`
- **Description**: Fetches step-by-step citizen guides from `/data/real/guides` covering Banking (DBT, Aadhaar linking), Aadhaar/PAN, Ration Cards, Health (ASHA), and Family Documentation.
- **Parameters**:
  - `topic` (string): Topic key (`banking`, `aadhaar_pan`, `ration`, `health`, `family`)

## 7. `export_summary`
- **Description**: Prepares a concise printable or voice summary of the household benefits, eligibility matches, and pending document checklists.
- **Parameters**: None
