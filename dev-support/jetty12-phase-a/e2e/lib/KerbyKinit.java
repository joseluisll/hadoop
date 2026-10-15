/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import java.io.File;

import org.apache.kerby.kerberos.kerb.client.KrbClient;
import org.apache.kerby.kerberos.kerb.type.ticket.TgtTicket;

/**
 * kinit for hosts without the MIT Kerberos tools: gets a TGT from a keytab
 * with the Kerby client library hadoop-minikdc is built on, and stores it
 * in a credentials cache that Hadoop clients and curl read.
 *
 * Run as a single-file program on the MiniKdc classpath:
 * java -cp 'minikdc/*' KerbyKinit.java KRB5_CONF_DIR KEYTAB PRINCIPAL CCACHE
 */
public final class KerbyKinit {
  public static void main(String[] args) throws Exception {
    if (args.length != 4) {
      System.err.println("Usage: KerbyKinit KRB5_CONF_DIR KEYTAB PRINCIPAL CCACHE");
      System.exit(2);
    }
    KrbClient client = new KrbClient(new File(args[0]));
    client.init();
    TgtTicket tgt = client.requestTgt(args[2], new File(args[1]));
    client.storeTicket(tgt, new File(args[3]));
    System.out.println("Ticket for " + args[2] + " stored in " + args[3]);
  }
}
