A secure backend API layer is needed to bridge the S3 hosted react dashboard bucket: central-va-tree-canopy-dashboard and the PostgreSQL database on your EC2 instance using an AWS Lambda function writen in python to be paired with an AWS API Gateway HTTP API.
Grant Lambda Access to your Database
    - Open the VPC Console and click Security Groups, then click Create security group.Name: tree-canopy-lambda-sgVPC: tree-canopy-vpcInbound Rules: Leave completely blank (nothing needs to call Lambda directly via IP).Outbound Rules: Leave as default (Allow all outbound).
    - Open your existing EC2 Database Security Group (tree-canopy-ec2-db-sg).Click Edit inbound rules.Add a new rule: Type: PostgreSQL (5432) | Source: Select tree-canopy-lambda-sg.Click Save rules
Create the Lambda IAM Execution Role
    - Open the IAM Console, click Roles, then click Create role.Select AWS Service as the trusted entity type, and choose Lambda from the service dropdown.Search for and attach the following managed policies:AWSLambdaVPCAccessExecutionRole (Crucial: Allows Lambda to run inside your private subnets).AmazonSSMReadOnlyAccess or SecretsManagerReadWrite (Recommended: Keeps database passwords out of your raw code).Name the role tree-canopy-backend-lambda-role and click Create role.
Write and Deploy the Lambda Function
    - Because the Tree Canopy Dashboard React application needs JSON outputs, the Lambda function will execute a query and structure the response payload.
    - Open the AWS Lambda Console and click Create function.Choose Author from scratch:Function name: tree-canopy-api-backendRuntime: Select Python 3.11 (or your preferred language).Permissions: Expand the tab and choose Use an existing role, selecting tree-canopy-backend-lambda-role.Scroll down to the Advanced settings section:Check Enable VPC.VPC: Select tree-canopy-vpc.Subnets: Select both tree-canopy-private-1a and tree-canopy-private-1b.Security groups: Select tree-canopy-lambda-sg.Click Create function.
Create a database layer for the Lambda function using Docker
Configure the HTTP API Gateway
    - Now, we need to expose Lambda function: tree-canopy-api-backend to the public internet using an HTTP API.
    - Open the Amazon API Gateway Console and click Create API.Find HTTP API and click Build.Configure integrations:Select Lambda.
    - Select your AWS Region and choose tree-canopy-api-backend.API name: tree-canopy-public-gateway.Configure routes:Set the Method to GET.
    - Set the Resource path to /assets.Configure stages: Leave as $default with Auto-deploy enabled.
    - Here is the generated Invoke URL: https://rqmo3xlicl.execute-api.us-east-1.amazonaws.com
Enable CORS (Cross-Origin Resource Sharing)
    - Since the Tree Canopy Dashboard React application sits on a different domain (CloudFront), the browser will block requests unless API Gateway explicitly allows it.In your API Gateway menu, click CORS under the Develop column.Click Configure and add the following wildcard values for development (restrict these to your CloudFront URL later before going to production):Access-Control-Allow-Origin: *Access-Control-Allow-Methods: GET, OPTIONSAccess-Control-Allow-Headers: content-typeClick Save.
Now it is time to test database access from the Tree Canopy Dashboard React application