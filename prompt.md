We want to have a web-interface to manage access groups for the users of our catalysis metadata organizer (../). Scicat already has 
predefined CASL authorization model, with some vanilla group lists. I hope to get a web app that will allow:
 - create and manage different groups
 - add group to the group lists for dataset, orig datablocks, users, proposals, jobs, instruments and samples
 - allow to add/delete some user (visible via LDAP server) to a given group 

 It would be nice if you could inspect first the scicat documentation under:
 https://www.scicatproject.org/documentation/Development/v4.x/backend/authorization.html
 https://www.scicatproject.org/documentation/Development/v4.x/backend/authorization/authorization_datasets.html
 https://www.scicatproject.org/documentation/Development/v4.x/backend/authorization/authorization_users.html
 https://www.scicatproject.org/documentation/Development/v4.x/backend/authorization/authorization_proposals.html
 https://www.scicatproject.org/documentation/Development/v4.x/backend/authorization/authorization_jobs.html
 https://www.scicatproject.org/documentation/Development/v4.x/backend/authorization/authorization_origdatablocks.html
 https://www.scicatproject.org/documentation/Development/v4.x/backend/authorization/authorization_instruments.html
 https://www.scicatproject.org/documentation/Development/v4.x/backend/authorization/authorization_users.html
 https://www.scicatproject.org/documentation/Development/v4.x/backend/authorization/authorization_samples.html

 Make a necessary research of the scicat repository for additional information.

 We already have a scicat instance running locally, so you can inspect the API if needed.

After the research, tell me what's missing in the actual scicat but is needed to cover the functionality. We want
to have an access right management for a catalytic research lab in a university. That means, there can be numerous research groups,
projects, proposals and data sources (instruments). There are also temporary positions such as student or postdoc, so that 
the ownership/access expiration and automatic transfer should be envisioned too.

For implementation it's nice if we can use react/vite stack which is already used for the main catorga project.
I hope that you can propose and implement an intuitive GUI with necessary functionality. This seems like a commonly
developed instrument and probably you can find design and UI examples from existing solutions.
