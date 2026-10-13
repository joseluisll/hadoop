# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# hadoop-common command line, and loading of the classes phase A moves
# between jars through every launcher's classpath.

COMPONENT=common-cli

cli version --expect-regex '^Hadoop (\S+)' -- hadoop version
cli classpath -- hadoop classpath
cli envvars -- hadoop envvars
cli conftest -- hadoop conftest
cli checknative --expect-rc 0,1 -- hadoop checknative -a
cli jnipath -- hadoop jnipath
cli credential-create -- hadoop credential create jetty12.alias -value s3cr3t \
  -provider "localjceks://file${RUN}/tmp/creds.jceks"
cli credential-list --expect-regex '(jetty12\.alias)' -- hadoop credential list \
  -provider "localjceks://file${RUN}/tmp/creds.jceks"
local_dir="${RUN}/tmp/localfs"
mkdir -p "${local_dir}"
printf 'line one\nline two\n' > "${local_dir}/in.txt"
cli localfs-ls -- hadoop fs -ls "file://${local_dir}"
cli localfs-cat --shape sha256 -- hadoop fs -cat "file://${local_dir}/in.txt"
cli localfs-checksum -- hadoop fs -checksum "file://${local_dir}/in.txt"

# Classes whose jar changes in phase A (javax.annotation), and the Jetty,
# servlet, JAX-RS and Jersey classes the web servers are built on, loaded
# through each launcher's real classpath.
CLASSES=(
  javax.annotation.PostConstruct
  javax.annotation.PreDestroy
  javax.annotation.Priority
  javax.annotation.Resource
  javax.annotation.security.RolesAllowed
  javax.servlet.Filter
  javax.servlet.http.HttpServlet
  javax.ws.rs.core.Application
  javax.ws.rs.ext.MessageBodyReader
  org.eclipse.jetty.server.Server
  org.eclipse.jetty.server.handler.ContextHandlerCollection
  org.eclipse.jetty.http.HttpField
  org.eclipse.jetty.http.MimeTypes
  org.eclipse.jetty.util.ssl.SslContextFactory
  org.eclipse.jetty.servlet.ServletContextHandler
  org.eclipse.jetty.webapp.WebAppContext
  org.eclipse.jetty.security.ConstraintSecurityHandler
  org.glassfish.jersey.server.ResourceConfig
  org.glassfish.jersey.servlet.ServletContainer
  org.glassfish.jersey.jettison.JettisonFeature
  com.fasterxml.jackson.jaxrs.json.JacksonJsonProvider
  org.apache.hadoop.http.HttpServer2
)
for launcher in hadoop hdfs yarn mapred; do
  for cls in "${CLASSES[@]}"; do
    # FindClass exits 0 when the class loads, 3 when it is not on the
    # classpath, 4 when loading fails, and prints the jar it came from. The
    # exit code and the jar must be the same on both sides.
    cli "load.${launcher}.${cls}" --expect-rc 0,3 \
      --expect-regex "(?m)^${cls//./\\.}: file:\\S*/([^/\\s]+)\\.jar\$|^()Class not found" \
      -- sh -c '"$0" org.apache.hadoop.util.FindClass load "$1" 2>&1' "${launcher}" "${cls}"
  done
done
