package example;

import java.security.interfaces.RSAPublicKey;
import java.util.Properties;
import org.apache.hadoop.security.authentication.util.CertificateUtil;

/**
 * Exercises the HADOOP-19971 surface from outside Hadoop and reports what it
 * finds. Compiled against one Hadoop ref, run against another.
 */
public final class Consumer {

  /** A self-signed test certificate, PEM body only. */
  private static final String PEM =
      "MIICwTCCAamgAwIBAgIIaLcM+GYS+zcwDQYJKoZIhvcNAQEMBQAwDzENMAsGA1UEAxMEdGVzdDAe"
      + "Fw0yNjA4MjUwODMwNTlaFw0zNjA4MjIwODMwNTlaMA8xDTALBgNVBAMTBHRlc3QwggEiMA0GCSqG"
      + "SIb3DQEBAQUAA4IBDwAwggEKAoIBAQC2raZa9FBNv+6UQiL14jhbtRAszqm5bxGf6d1fRnlIUxVg"
      + "8X3aOLyVbXhKw/Ewe+anhXL6zvwrHdJ+HL1NoUeMVsbQVS8I0alQ7qLMFCeXeN9bnfuDml78Fky+"
      + "C3tT/l9q6mF43Lnd3mRwfrjurN4eeGUMrQVq2psPZthtX4Hoilqp+JlQ1dDJ4VGAGDYJjwylRJ+Z"
      + "cViwYexJtKL8rxFMlIYAR/4xZUsaVcjHrAv0KVyxplKAPSc8uiCUbozFs9svE14wK4JELSb9S2w6"
      + "N21JSixCs0qUq+0KyyOEdquqP+6lpEq5ld9hJ8mtHAV3yvZJyf0IVGCBFdaKvtG92N4DAgMBAAGj"
      + "ITAfMB0GA1UdDgQWBBS9saIdJs9MRYcd4yyjUgpKCOl85jANBgkqhkiG9w0BAQwFAAOCAQEAd/1F"
      + "D1OdBlXbpAtm7qi4Gh6wkfWmGxI38Tre79lMY9/DX5Wh+9wVYbOre7e4bcEk8MO/GLj0QnSIyHXU"
      + "N0esgFWrnfMnbyI922KSgNrtZVDHXJ/pGA6pu5wMiPMK7M7w6Lvzs8Ir6iMmleTWumrlehTB2TeM"
      + "PZYPKiRD1RJTnJapeJgkvL2HbafMDTSR7LIk3c8G70SpcAWN++A3MQeN7AluAiPeRXbiAbVfP1tb"
      + "HPIQir/8OfFH9k3cpAD8ASoYwZ4udQKV87z/OuBOvdtdT+SBcxWBrVupGnJj5KR1wKdAETVde8S4"
      + "e9Myc4G09602ZNfdLEtwJrB4n6ISmEExuw==";

  public static void main(String[] args) throws Exception {
    int failures = 0;

    System.out.println("== servlet API on the classpath ==");
    System.out.println("  javax.servlet.ServletContext -> " + originOf(
        "javax/servlet/ServletContext.class"));
    System.out.println("  SignerSecretProvider         -> " + originOf(
        "org/apache/hadoop/security/authentication/util/SignerSecretProvider.class"));

    System.out.println("== the deprecated bridge ==");
    LegacySecretProvider provider = new LegacySecretProvider();
    provider.init(new Properties(), null, 4242L);
    if (provider.wasInitCalled() && provider.recordedValidity() == 4242L) {
      System.out.println("  PASS init() reached the provider, tokenValidity carried through");
    } else {
      System.out.println("  FAIL init() did not reach the provider: called="
          + provider.wasInitCalled() + " validity=" + provider.recordedValidity());
      failures++;
    }
    if (provider.getCurrentSecret() != null) {
      System.out.println("  PASS getCurrentSecret() returned a secret");
    } else {
      System.out.println("  FAIL getCurrentSecret() returned null");
      failures++;
    }

    System.out.println("== CertificateUtil ==");
    try {
      RSAPublicKey key = CertificateUtil.parseRSAPublicKey(PEM);
      System.out.println("  PASS parseRSAPublicKey returned a "
          + key.getAlgorithm() + " key of " + key.getModulus().bitLength() + " bits");
    } catch (Throwable t) {
      System.out.println("  FAIL parseRSAPublicKey: " + t);
      failures++;
    }

    System.out.println(failures == 0 ? "RESULT: PASS" : "RESULT: FAIL (" + failures + ")");
    System.exit(failures == 0 ? 0 : 1);
  }

  /** Which jar a class was loaded from. */
  private static String originOf(String resource) {
    java.net.URL url = Consumer.class.getClassLoader().getResource(resource);
    if (url == null) {
      return "NOT ON CLASSPATH";
    }
    String s = url.toString();
    int bang = s.indexOf('!');
    if (bang > 0) {
      s = s.substring(0, bang);
    }
    return s.substring(s.lastIndexOf('/') + 1);
  }
}
