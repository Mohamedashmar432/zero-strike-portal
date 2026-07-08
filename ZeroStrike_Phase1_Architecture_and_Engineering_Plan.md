# ZeroStrike Platform -- Phase 1 Architecture & Engineering Plan

## Overview

This document defines the Phase 1 architecture for the ZeroStrike
Platform. The goal is to build a simple, scalable SaaS platform that
integrates with the independent Go-based ZeroStrike SAST scanner.

The platform is responsible for:

-   User authentication
-   Project management
-   API key management
-   Scan orchestration
-   Report management
-   Audit logging

The Go scanner remains completely independent and communicates only
through REST APIs.

------------------------------------------------------------------------

# High-Level Architecture

``` text
                   ZeroStrike Platform

             Next.js + Tailwind + shadcn/ui

                        │
                  HTTPS REST API
                        │
                FastAPI (Python Backend)
                        │
      ┌────────────────────────────────────┐
      │ Authentication                     │
      │ User Management                    │
      │ Projects                           │
      │ Scan Management                    │
      │ API Keys                           │
      │ Cloud Scan                         │
      │ Report Management                  │
      │ Audit Logs                         │
      └────────────────────────────────────┘
                        │
                  MongoDB Atlas
                        │
        ------------------------------------
        │                                  │
 Local Go Scanner                 Cloud Scan Worker
```

------------------------------------------------------------------------

# Technology Stack

  Layer              Technology
  ------------------ --------------------------
  Frontend           Next.js 15
  UI                 Tailwind CSS + shadcn/ui
  State Management   TanStack Query
  Forms              React Hook Form + Zod
  Backend            FastAPI
  Authentication     JWT + Refresh Tokens
  Database           MongoDB Atlas
  MongoDB ODM        Beanie
  Background Tasks   FastAPI BackgroundTasks
  Scanner            Go CLI
  Reports            JSON + HTML
  Logging            Structlog
  Deployment         Docker Compose

No Redis, Celery, RabbitMQ, or Kubernetes are required for Phase 1.

------------------------------------------------------------------------

# User Roles

## Admin

-   View all projects
-   Manage all users
-   View all reports
-   Access system settings
-   View audit logs

## User

-   Create projects
-   Invite collaborators
-   View own projects
-   Run scans
-   Generate API keys

------------------------------------------------------------------------

# Project Structure

Each project contains:

-   Overview
-   Scans
-   Reports
-   Members
-   API Keys
-   Settings

------------------------------------------------------------------------

# Local Scan Workflow

1.  User creates a project.
2.  User generates a project API key.
3.  User selects an expiration date.
4.  User downloads the appropriate scanner.
5.  User copies the generated CLI command.
6.  Scanner validates the API key.
7.  Server returns a Scan ID.
8.  Scanner performs the scan.
9.  Scanner uploads:
    -   JSON results
    -   HTML report
10. Scan is marked complete.
11. Report becomes available in the project.

Example:

``` bash
zerostrike scan \
  --project-id proj_123 \
  --server https://portal.zerostrike.ai \
  --token zst_xxxxxxxxx
```

------------------------------------------------------------------------

# Cloud Scan Workflow

1.  User selects Cloud Scan.
2.  Choose source:
    -   GitHub
    -   Azure DevOps
    -   GitLab
3.  Authenticate using OAuth.
4.  Select repository.
5.  Select branch.
6.  Platform clones repository into a temporary directory.
7.  Execute Go scanner.
8.  Store JSON + HTML reports.
9.  Delete cloned repository.

Source code is never stored permanently.

------------------------------------------------------------------------

# CI/CD Workflow

The platform generates project-specific pipeline snippets.

Example:

``` yaml
steps:
  - name: ZeroStrike Scan
    run: |
      curl -L https://download.zerostrike.ai/install.sh | bash

      zerostrike scan \
        --project-id proj_123 \
        --server https://portal.zerostrike.ai \
        --token $ZEROSTRIKE_TOKEN
```

Supported providers:

-   GitHub Actions
-   Azure Pipelines
-   GitLab CI

------------------------------------------------------------------------

# Dashboard

Display:

-   Total Projects
-   Total Scans
-   Critical Findings
-   High Findings
-   Recent Scans
-   Latest Reports

------------------------------------------------------------------------

# Audit Logs

Track:

-   Login
-   Logout
-   Project Created
-   Project Deleted
-   Scan Started
-   Scan Completed
-   API Key Created
-   API Key Revoked
-   User Invited
-   Member Removed

------------------------------------------------------------------------

# MongoDB Collections

-   users
-   projects
-   project_members
-   api_keys
-   scans
-   findings
-   reports
-   audit_logs

------------------------------------------------------------------------

# REST API Versioning

    /api/v1/auth
    /api/v1/users
    /api/v1/projects
    /api/v1/apikeys
    /api/v1/scans
    /api/v1/reports

------------------------------------------------------------------------

# Future Expansion

Additional modules can be added without redesign:

-   DAST
-   SCA
-   Secrets Scanning
-   Container Security
-   Compliance
-   AI Autofix
-   Attack Surface Management

------------------------------------------------------------------------

# Sprint Plan

## Sprint 1 -- Foundation

-   Project initialization
-   Next.js setup
-   FastAPI setup
-   MongoDB Atlas integration
-   JWT authentication
-   Admin/User roles
-   User profile
-   Audit logging
-   Environment configuration

Deliverable: Working authentication and user management.

------------------------------------------------------------------------

## Sprint 2 -- Projects & API Keys

-   Project CRUD
-   Project members
-   API key generation
-   Expiration support
-   Token revocation
-   Token validation endpoint

Deliverable: Project management and secure scanner authentication.

------------------------------------------------------------------------

## Sprint 3 -- Local Scanner Integration

-   Create scan sessions
-   Validate project token
-   Upload JSON
-   Upload HTML
-   Store metadata
-   Display reports

Deliverable: Local scanner fully integrated.

------------------------------------------------------------------------

## Sprint 4 -- Cloud Scanning

-   GitHub OAuth
-   Azure DevOps OAuth
-   GitLab OAuth
-   Repository selection
-   Branch selection
-   Temporary repository cloning
-   Execute Go scanner
-   Upload reports
-   Delete temporary repository

Deliverable: Cloud scanning support.

------------------------------------------------------------------------

## Sprint 5 -- CI/CD Integration

-   GitHub Actions template
-   Azure Pipelines template
-   GitLab CI template
-   Documentation
-   Scan history improvements

Deliverable: Pipeline integrations.

------------------------------------------------------------------------

## Sprint 6 -- Dashboard & Polish

-   Dashboard widgets
-   Report downloads
-   Search & filtering
-   Audit log UI
-   Responsive design
-   Testing
-   Documentation

Deliverable: Production-ready Phase 1 MVP.

------------------------------------------------------------------------

# Guiding Principles

-   Keep the platform monolithic.
-   Keep the scanner independent.
-   Avoid unnecessary infrastructure.
-   Use REST APIs for all scanner communication.
-   Store JSON as the source of truth.
-   Store HTML as a downloadable artifact.
-   Design with future AI modules in mind without introducing premature
    complexity.
