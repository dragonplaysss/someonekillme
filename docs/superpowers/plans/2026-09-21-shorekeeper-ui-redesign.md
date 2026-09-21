# Shorekeeper UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completely redesign Shorekeeper's response presentation to achieve WICK-level information density with clean Discord-native UI, Shorekeeper personality, custom emojis, and centralized webhook/embed rendering.

**Architecture:** Extend the existing ResponseEngine class in cogs/core/responses.py to create a ShorekeeperUI system that centralizes all response creation. Update the footer to show dynamic time, implement custom emoji registry with fallbacks, and ensure lightweight implementation without repeated resource loading.

**Tech Stack:** Python, discord.py

**Spec:** This plan implements the Shorekeeper UI/Webhook rework requirements from the user instructions.

## Global Constraints

- Do not modify internal logic/architecture of roblox_auth.py, roblox_snipe.py, Anti-Nuke logic, moderation authorization/hierarchy, command parser, guild activation/module authorization, credential delivery, or Roblox account storage
- Preserve existing behavior and data flow of underlying systems
- Only change how results are rendered/sent, not the internal logic
- Implement centralized emoji registry with custom Discord emoji IDs where available and Unicode fallbacks where unavailable
- Remove Wuthering Waves from bot UI/footer
- Keep implementation lightweight: no image loading per command, no repeated webhook creation, no repeated emoji lookups
- After implementation run: pytest -q, python -m compileall -q ., git diff --check

---
### Task 1: Analyze Current Response Systems

**Files:**
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\responses.py
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\shorekeeper_responses.py
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\constants.py

**Interfaces:**
- Consumes: None
- Produces: Analysis of current response engine and shorekeeper_responses systems

- [ ] **Step 1: Examine current ResponseEngine class** to understand its methods and usage patterns
- [ ] **Step 2: Examine current ShorekeeperResponses and ShorekeeperEmojis classes** to understand emoji handling
- [ ] **Step 3: Check constants for EMBED_FOOTER and color definitions**
- [ ] **Step 4: Verify which system is actually used throughout the codebase**
- [ ] **Step 5: Document findings and confirm approach for refactoring**

### Task 2: Create ShorekeeperUI Class with Dynamic Footer

**Files:**
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\responses.py

**Interfaces:**
- Consumes: Existing ResponseEngine class structure
- Produces: ShorekeeperUI class with dynamic timestamp footer

- [ ] **Step 1: Create ShorekeeperUI class** that extends or replaces ResponseEngine
- [ ] **Step 2: Implement dynamic footer** that shows "Shorekeeper • Today at <current_time>" in HH:MM format
- [ ] **Step 3: Preserve all existing methods** (success, failure, warning, etc.) from ResponseEngine
- [ ] **Step 4: Ensure backward compatibility** with existing response_engine usage
- [ ] **Step 5: Update the global response_engine instance** to be ShorekeeperUI instead of ResponseEngine

### Task 3: Implement Centralized Emoji Registry

**Files:**
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\responses.py
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\shorekeeper_responses.py

**Interfaces:**
- Consumes: Existing ShorekeeperEmojis class
- Produces: Enhanced emoji system with specific Shorekeeper emojis and fallback chain

- [ ] **Step 1: Define required Shorekeeper emojis**: shore_success, shore_love, shore_verify, shore_warning, shore_roblox, shore_confused, shore_moderation, shore_security, shore_error
- [ ] **Step 2: Update ShorekeeperEmojis._custom_emojis mapping** with the new emoji names
- [ ] **Step 3: Keep existing Unicode fallbacks** for backward compatibility
- [ ] **Step 4: Keep existing text fallbacks** as last resort
- [ ] **Step 5: Ensure get() method maintains fallback chain**: custom → Unicode → text
- [ ] **Step 6: Add helper method** to get emoji with optional size/scale parameters if needed

### Task 4: Update Color Constants (if needed)

**Files:**
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\constants.py

**Interfaces:**
- Consumes: Existing color constants
- Produces: Updated color constants matching Shorekeeper theme

- [ ] **Step 1: Review existing color definitions** for SUCCESS, ERROR, WARNING, INFO, SECURITY
- [ ] **Step 2: Verify colors match Shorekeeper/Wuthering Waves inspiration** (keep if appropriate)
- [ ] **Step 3: Update any colors** that don't match the desired Shorekeeper aesthetic
- [ ] **Step 4: Ensure color usage** in response methods remains correct

### Task 5: Create Centralized Response Methods for Specific Use Cases

**Files:**
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\responses.py

**Interfaces:**
- Consumes: ShorekeeperUI class
- Produces: Specialized response methods for different scenarios

- [ ] **Step 1: Add moderation() method** for moderation actions (warn, mute, kick, ban, etc.)
- [ ] **Step 2: Add security() method** for anti-nuke and security alerts
- [ ] **Step 3: Add verification() method** for verification processes
- [ ] **Step 4: Add roblox() method** for Roblox Auth responses
- [ ] **Step 5: Add snipe() method** for Roblox Snipe responses
- [ ] **Step 6: Add music() method** for music-related responses
- [ ] **Step 7: Add settings() method** for configuration responses
- [ ] **Step 8: Add help() method** for help and documentation responses
- [ ] **Step 9: Each method should use appropriate emoji, color, and title formatting**

### Task 6: Update Embed Construction for Consistent UI Structure

**Files:**
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\responses.py

**Interfaces:**
- Consumes: ShorekeeperUI class methods
- Produces: Consistent embed structure matching Discord-native UI guidelines

- [ ] **Step 1: Modify embed construction** to follow the specified structure:
  ```
  [EMOJI] TITLE
  
  Short contextual description.
  
  ────────────────
  
  Target       @User
  Moderator    @Moderator
  Action       Mute
  Duration     10 minutes
  Reason       Spam
  Case         #1042
  
  Shorekeeper • Today at 23:27
  ```
- [ ] **Step 2: Ensure only relevant fields are shown** (don't overload simple responses)
- [ ] **Step 3: Implement field rendering logic** that conditionally adds fields based on provided data
- [ ] **Step 4: Maintain existing method signatures** for backward compatibility
- [ ] **Step 5: Test that complex responses still work correctly**

### Task 7: Implement Webhook Usage with Fallback

**Files:**
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\responses.py

**Interfaces:**
- Consumes: ShorekeeperUI class
- Produces: Webhook-capable response sending with normal bot fallback

- [ ] **Step 1: Add webhook detection logic** to determine if webhooks are available/usable
- [ ] **Step 2: Modify send methods** to use webhooks when appropriate and permitted
- [ ] **Step 3: Implement fallback to normal bot messages** when webhooks unavailable
- [ ] **Step 4: Ensure UI structure is preserved** regardless of sending method
- [ ] **Step 5: Cache webhook information** to avoid repeated creation/lookup
- [ ] **Step 6: Preserve existing interaction/response handling** for Discord interactions

### Task 8: Remove Wuthering Waves References from UI

**Files:**
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\responses.py
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\shorekeeper_responses.py
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\constants.py

**Interfaces:**
- Consumes: Existing footer and UI text
- Produces: UI with Wuthering Waves removed from user-facing elements

- [ ] **Step 1: Update EMBED_FOOTER constant** in constants.py to remove "Wuthering Waves"
- [ ] **Step 2: Update any hardcoded footer references** in responses.py
- [ ] **Step 3: Update ShorekeeperResponses.create_embed** method footer
- [ ] **Step 4: Ensure internal/project references** are preserved if not displayed to users
- [ ] **Step 5: Verify no "Wuthering Waves" text appears** in any user-facing embeds or messages

### Task 9: Optimize for Performance and Lightweight Implementation

**Files:**
- Modify: C:\Users\sarat\Desktop\Shorekeeper revival\cogs\core\responses.py

**Interfaces:**
- Consumes: ShorekeeperUI class
- Produces: Lightweight implementation without repeated resource loading

- [ ] **Step 1: Ensure emoji IDs are resolved once** and cached rather than looked up per command
- [ ] **Step 2: Avoid loading image files** every command or creating images on the fly
- [ ] **Step 3: Prevent repeated webhook creation** - cache webhook information
- [ ] **Step 4: Avoid repeatedly querying Discord** for emoji information - cache emoji data
- [ ] **Step 5: Prevent duplicate emoji registries** - maintain single source of truth
- [ ] **Step 6: Use efficient data structures** for emoji lookup and caching
- [ ] **Step 7: Validate that timestamp generation** is efficient and doesn't cause performance issues

### Task 9: Update Module-Specific Response Usage (Where Beneficial)

**Files:**
- Modify: Various cog files that manually construct embeds

**Interfaces:**
- Consumes: Existing manual embed constructions
- Produces: Refactored usage of ShorekeeperUI where it provides clear benefit

- [ ] **Step 1: Identify cog files** that manually construct embeds using response_engine.build() or similar
- [ ] **Step 2: Determine where migration to ShorekeeperUI methods** provides clear benefit (complex responses with multiple fields)
- [ ] **Step 3: Update anti_nuke.py** to use new security() and moderation() methods where appropriate
- [ ] **Step 4: Update moderation/moderation_core.py** to use new moderation() methods
- [ ] **Step 5: Update roblox_auth.py** to use new roblox() methods
- [ ] **Step 6: Update roblox_snipe.py** to use new snipe() methods
- [ ] **Step 7: Preserve existing behavior** - only change response formatting, not underlying logic
- [ ] **Step 8: Leave simple responses unchanged** if migration doesn't provide significant benefit
- [ ] **Step 8: Ensure all changes maintain backward compatibility**

### Task 10: Test and Verify Implementation

**Files:**
- Modify: None (testing only)

**Interfaces:**
- Consumes: All modified files
- Produces: Verified implementation

- [ ] **Step 1: Run pytest -q** to ensure no regressions
- [ ] **Step 2: Run python -m compileall -q .** to check for syntax errors
- [ ] **Step 3: Run git diff --check** to ensure no trailing whitespace issues
- [ ] **Step 4: Manually test key response types** (success, error, warning, moderation, security, etc.)
- [ ] **Step 5: Verify emoji fallback chain works** (custom → Unicode → text)
- [ ] **Step 6: Verify footer shows current time** in correct format
- [ ] **Step 7: Verify UI structure matches specifications**
- [ ] **Step 8: Confirm no "Wuthering Waves" appears** in user-facing elements
- [ ] **Step 9: Verify existing functionality** of roblox auth, snipe, anti-nuke, etc. is preserved